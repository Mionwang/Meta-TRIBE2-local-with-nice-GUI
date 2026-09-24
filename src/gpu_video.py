"""Keep the official V-JEPA2 backbone but load its weights in bf16 on CUDA.

The upstream neuralset extractor loads V-JEPA2 in float32 (~3.85 GiB of
weights). That leaves too little room for its 64-frame forward on an 8 GiB
GPU. This patch changes only the execution precision; features are cast back
to float32 before upstream aggregation and cache writes.
"""

def enable_bf16_vjepa2() -> None:
    import torch
    from neuralset.extractors.video import _HFVideoModel

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("This GPU/PyTorch build does not support CUDA bf16; use --video-device cpu")
    if getattr(_HFVideoModel, "_reel_bf16", False):
        return
    original_init = _HFVideoModel.__init__
    original_predict = _HFVideoModel.predict_hidden_states

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if "vjepa2" in self.model_name.lower():
            self.model.to(dtype=torch.bfloat16)

    def predict(self, images, audio=None):
        if "vjepa2" not in self.model_name.lower() or self.model.device.type != "cuda":
            return original_predict(self, images, audio)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            features = original_predict(self, images, audio)
        return features.float()

    _HFVideoModel.__init__ = init
    _HFVideoModel.predict_hidden_states = predict
    _HFVideoModel._reel_bf16 = True
