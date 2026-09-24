"""Run TRIBE v2's feature encoders on Apple Silicon GPUs (Metal / MPS).

neuralset only accepts "cpu" / "cuda" / "auto" as a device in its config, and
"auto" never picks MPS. Rather than edit the installed packages, this module
patches the few places where models are placed on a device:

* V-JEPA2 video encoder (neuralset ``_HFVideoModel``): moved to ``mps`` right after
  loading, run under float16 autocast. If a clip ever produces NaN/inf in half
  precision, that clip is recomputed in float32 and the model stays in float32.
* Wav2Vec-BERT audio encoder (neuralset ``HuggingFaceAudio``): moved to ``mps``.

The neuralset config still says "cpu" for these extractors, so cache keys (which
already exclude the device) are unchanged and cached features are portable.
Nothing here runs unless ``enable_mps()`` is called.
"""

from __future__ import annotations

import os
import platform
import warnings


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def mps_available() -> bool:
    try:
        import torch
        return bool(torch.backends.mps.is_available())
    except Exception:  # torch missing or built without MPS
        return False


def _empty_cache() -> None:
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


def enable_mps(*, video: bool = True, audio: bool = True) -> None:
    import torch

    if not mps_available():
        raise RuntimeError("This Mac's PyTorch build cannot see the Apple GPU (MPS). "
                           "Use --video-device cpu or reinstall with setup.sh.")
    precision = os.environ.get("TRIBE_MPS_PRECISION", "fp16").lower()
    mps = torch.device("mps")

    if video:
        from neuralset.extractors.video import _HFVideoModel

        if not getattr(_HFVideoModel, "_tribe_mps", False):
            original_init = _HFVideoModel.__init__
            original_predict = _HFVideoModel.predict_hidden_states

            def init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                self.model.to(mps)
                self._tribe_half = precision == "fp16"

            def predict(self, images, audio=None):
                if self.model.device.type != "mps":
                    return original_predict(self, images, audio)
                if getattr(self, "_tribe_half", False):
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            with torch.autocast("mps", dtype=torch.float16):
                                out = original_predict(self, images, audio).float()
                        if torch.isfinite(out).all():
                            return out
                        print("MPS: half precision overflowed on a clip; switching V-JEPA2 to float32.")
                    except RuntimeError as exc:  # autocast unsupported on this macOS/torch
                        print(f"MPS: float16 autocast unavailable ({exc}); using float32.")
                    self._tribe_half = False
                    _empty_cache()
                return original_predict(self, images, audio).float()

            _HFVideoModel.__init__ = init
            _HFVideoModel.predict_hidden_states = predict
            _HFVideoModel._tribe_mps = True

    if audio:
        from neuralset.extractors.audio import HuggingFaceAudio

        if not getattr(HuggingFaceAudio, "_tribe_mps", False):
            # Patch every subclass that defines its own loader (Wav2VecBert, Wav2Vec, ...).
            classes = [HuggingFaceAudio, *_all_subclasses(HuggingFaceAudio)]
            for cls in classes:
                if "_get_sound_model" in cls.__dict__:
                    cls._get_sound_model = _wrap_loader(cls.__dict__["_get_sound_model"], mps)
            HuggingFaceAudio._process_wav = _process_wav_on_model_device
            HuggingFaceAudio._tribe_mps = True


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def _wrap_loader(loader, device):
    def wrapped(self, model_name):
        model = loader(self, model_name)
        return model.to(device)
    return wrapped


def _process_wav_on_model_device(self, wav):
    """Same as neuralset's HuggingFaceAudio._process_wav, but sends inputs to the
    model's actual device instead of the configured ``self.device`` string."""
    import torch

    features = self._get_features(wav)
    device = next(self.model.parameters()).device
    with torch.no_grad():
        outputs = self.model(features.to(device), output_hidden_states=True)
    if self.layer_type == "transformer":
        out = outputs.get("hidden_states")
    elif self.layer_type == "convolution":
        out = outputs.get("extract_features")
    else:
        raise ValueError(f"Unknown layer type: {self.layer_type}")
    if isinstance(out, tuple):
        out = torch.stack(out)
    out = out.squeeze(1).detach().float().cpu().clone().transpose(-1, -2).numpy()
    if not self.cache_all_layers and self.cache_n_layers is None:
        out = self._aggregate_layers(out)
    return torch.Tensor(out)
