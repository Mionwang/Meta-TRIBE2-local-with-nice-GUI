"""Run local, staged Meta TRIBE v2 inference on short video or audio."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
MODEL_REVISION = "f894e783020944dcd96e5568550afe2aa9743f9f"


def configure_cache() -> None:
    cache = ROOT / "cache"
    # The venv's own script folder (.venv\\Scripts on Windows, .venv/bin on macOS).
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    # Let the few PyTorch ops that Metal lacks fall back to CPU instead of crashing.
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    for name in ("models", "features", "atlas", "mne", "temp"):
        (cache / name).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache / "models"))
    os.environ.setdefault("MNE_DATA", str(cache / "mne"))
    os.environ.setdefault("MNE_DATASETS_SAMPLE_PATH", str(cache / "mne"))
    os.environ.setdefault("TMP", str(cache / "temp"))
    os.environ.setdefault("TEMP", str(cache / "temp"))
    try:
        import imageio_ffmpeg
        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
        os.environ["IMAGEIO_FFMPEG_EXE"] = str(exe)
        os.environ["FFMPEG_BINARY"] = str(exe)
        os.environ["PATH"] = str(exe.parent) + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_events(model, path: Path, include_audio: bool, include_language: bool):
    if path.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg"}:
        if include_language:
            return model.get_events_dataframe(audio_path=str(path))
        import pandas as pd
        from tribev2.demo_utils import get_audio_and_text_events
        event = pd.DataFrame([{"type": "Audio", "filepath": str(path), "start": 0,
                               "timeline": "default", "subject": "default"}])
        return get_audio_and_text_events(event, audio_only=True)
    if include_language:
        return model.get_events_dataframe(video_path=str(path))
    import pandas as pd
    from tribev2.demo_utils import get_audio_and_text_events
    event = pd.DataFrame([{"type": "Video", "filepath": str(path), "start": 0,
                           "timeline": "default", "subject": "default"}])
    if include_audio:
        # Official extraction without WhisperX/Llama. A file with no audio can
        # be processed by passing --no-audio explicitly.
        return get_audio_and_text_events(event, audio_only=True)
    from neuralset.events.utils import standardize_events
    return standardize_events(event)


def resolve_device(requested: str) -> str:
    """auto -> NVIDIA CUDA, else Apple Silicon MPS, else CPU."""
    import torch
    from apple_silicon import mps_available

    if requested == "auto":
        if torch.cuda.is_available():
            return "cuda"
        return "mps" if mps_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA PyTorch cannot see an NVIDIA GPU. Run diagnostics first, or use --video-device auto.")
    if requested == "mps" and not mps_available():
        raise RuntimeError("PyTorch cannot see the Apple GPU (MPS). Use --video-device cpu or rerun setup.sh.")
    return requested


def _empty_accelerator_cache() -> None:
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    try:
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


def infer(path: Path, *, video_device: str, head_device: str, include_audio: bool,
          include_language: bool) -> tuple[object, object]:
    import numpy as np
    import torch
    import yaml
    from einops import rearrange
    from huggingface_hub import snapshot_download
    from tribev2 import TribeModel

    if video_device == "cuda":
        from gpu_video import enable_bf16_vjepa2
        enable_bf16_vjepa2()
    audio_device = "cuda" if torch.cuda.is_available() else "cpu"
    if video_device == "mps":
        # neuralset's config only accepts cpu/cuda; the patch moves the encoders to Metal.
        from apple_silicon import enable_mps
        enable_mps(video=True, audio=True)
        print("Apple Silicon: V-JEPA2 and Wav2Vec-BERT run on the Metal GPU (MPS).")
    cfg = {
        "data.num_workers": 0,
        "data.batch_size": 1,
        "data.video_feature.image.batch_size": 1,
        "data.video_feature.image.device": "cpu" if video_device == "mps" else video_device,
        "data.audio_feature.device": audio_device,
        "data.text_feature.device": "cpu",
        "data.study.transforms.chunkvideos.infra.folder": str(ROOT / "cache" / "features"),
    }
    # The published config contains one Linux pathlib.PosixPath YAML object.
    # PyYAML's UnsafeLoader cannot instantiate that class on Windows. Decode
    # it as a plain string; the old training cache path is overridden above.
    yaml.UnsafeLoader.add_constructor(
        "tag:yaml.org,2002:python/object/apply:pathlib.PosixPath",
        lambda loader, node: "/".join(str(x).strip("/") for x in loader.construct_sequence(node)),
    )
    # Upstream converts a Hub repo ID to pathlib.Path. On Windows that turns
    # facebook/tribev2 into a backslash-separated ID rejected by HF Hub.
    # Download its two files first, then pass the local snapshot path.
    checkpoint = snapshot_download(repo_id="facebook/tribev2", revision=MODEL_REVISION,
                                   allow_patterns=["config.yaml", "best.ckpt"])
    print("Loading official TRIBE v2 checkpoint onto CPU...")
    model = TribeModel.from_pretrained(checkpoint, device="cpu",
        cache_folder=ROOT / "cache" / "features", config_update=cfg)
    events = make_events(model, path, include_audio, include_language)
    print("Extracting and caching available modalities...")
    print(f"Video encoder device: {video_device}; prediction model waits on CPU.")
    loaders = model.data.get_loaders(events=events, split_to_build="all")
    if "all" not in loaders:
        raise RuntimeError("The official TRIBE loader returned no clip segments.")
    gc.collect()
    _empty_accelerator_cache()
    head = model._model
    head.eval()

    def run_head(device: str):
        print(f"Running TRIBE prediction model on {device}...")
        head.to(device)
        preds, times = [], []
        with torch.inference_mode():
            for batch in loaders["all"]:
                batch = batch.to(head.device)
                segments = []
                for segment in batch.segments:
                    for t in np.arange(0, segment.duration - 1e-2, model.data.TR):
                        segments.append(segment.copy(offset=t, duration=model.data.TR))
                keep = np.array([len(s.ns_events) > 0 for s in segments], dtype=bool)
                y = rearrange(head(batch).detach().float().cpu().numpy(), "b d t -> (b t) d")
                if len(y) != len(keep):
                    raise RuntimeError(f"TRIBE output has {len(y)} rows for {len(keep)} TR segments")
                preds.append(y[keep])
                times.extend(float(s.start) for s, yes in zip(segments, keep) if yes)
                del batch, y
        return preds, times

    try:
        preds, times = run_head(head_device)
    except (RuntimeError, TypeError, NotImplementedError) as exc:
        if head_device != "mps":
            raise
        # The prediction head is small; if Metal lacks an op or dtype, CPU is fine.
        print(f"MPS could not run the prediction head ({exc}); retrying on CPU.")
        _empty_accelerator_cache()
        preds, times = run_head("cpu")
    if not preds or not len(times):
        raise RuntimeError("TRIBE produced no predictions; check video duration and event extraction.")
    result = np.concatenate(preds, axis=0)
    if len(times) != len(result):
        raise RuntimeError("TRIBE prediction/time alignment failed")
    del head, model, loaders
    gc.collect()
    _empty_accelerator_cache()
    return result, np.asarray(times)


def analyze_one(path: Path, args) -> None:
    import numpy as np
    from reel_metrics import write_results

    path = path.resolve()
    kind = "audio" if path.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg"} else "video"
    if not path.is_file() or path.suffix.lower() not in {".mp4", ".wav", ".mp3", ".flac", ".ogg"}:
        raise ValueError(f"Expected an existing MP4 or WAV/MP3/FLAC/OGG file: {path}")
    if kind == "audio" and args.no_audio:
        raise ValueError("Audio-only inputs cannot use --no-audio")
    output = ROOT / "OUTPUT" / path.stem
    output.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(path)
    key = {"sha256": digest, "kind": kind, "video_device": args.video_device,
           "head_device": args.head_device, "audio": not args.no_audio,
           "language": args.with_language, "model_revision": MODEL_REVISION,
           "pipeline_version": 2}
    cache_path = output / "cortical_activity.npz"
    state_path = output / "inference_state.json"
    cached = (cache_path.exists() and state_path.exists() and not args.force and
              json.loads(state_path.read_text(encoding="utf-8")) == key)
    if cached:
        print(f"Using cached cortical predictions for {path.name}")
        with np.load(cache_path, allow_pickle=False) as saved:
            preds, times = saved["preds"], saved["times"]
    else:
        print(f"Analyzing {path.name} ({path.stat().st_size / 1e6:.1f} MB)...")
        media_dir = ROOT / "cache" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        # The official audio transform writes a WAV alongside its MP4. Work on
        # a content-addressed local copy so INPUT and external folders stay clean.
        staged = media_dir / f"{digest[:20]}{path.suffix.lower()}"
        if not staged.exists() or staged.stat().st_size != path.stat().st_size:
            shutil.copy2(path, staged)
        preds, times = infer(staged, video_device=args.video_device, head_device=args.head_device,
                             include_audio=not args.no_audio, include_language=args.with_language)
        np.savez_compressed(cache_path, preds=preds.astype(np.float32), times=times)
        state_path.write_text(json.dumps(key, indent=2), encoding="utf-8")
    provenance = {"input": str(path), "input_kind": kind,
                  "source_kind": os.environ.get("TRIBE_SOURCE_KIND", kind),
                  "sha256": digest, "model": "facebook/tribev2",
                  "model_revision": MODEL_REVISION,
                  "video_encoder_device": args.video_device, "head_device": args.head_device,
                  "audio_included": not args.no_audio, "language_included": args.with_language,
                  "cached_predictions": cached}
    write_results(output, times, preds, provenance, ROOT / "cache" / "atlas")
    print(f"Done: {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Experimental local TRIBE v2 Reel analysis")
    parser.add_argument("video", nargs="?", type=Path, help="MP4 or audio path; omit to analyze all MP4s in INPUT")
    parser.add_argument("--video-device", choices=["auto", "cpu", "cuda", "mps"], default="auto",
                        help="V-JEPA2 device. auto = NVIDIA CUDA (bf16), else Apple Silicon MPS (fp16), else CPU")
    parser.add_argument("--head-device", choices=["auto", "cpu", "cuda", "mps"], default="auto")
    parser.add_argument("--no-audio", action="store_true", help="Use for silent video or video-only analysis")
    parser.add_argument("--with-language", action="store_true",
                        help="Experimental full WhisperX/Llama path; requires gated Llama access")
    parser.add_argument("--force", action="store_true", help="Recompute cortical predictions")
    args = parser.parse_args()
    if args.no_audio and args.with_language:
        parser.error("--no-audio and --with-language cannot be combined")
    configure_cache()
    try:
        args.video_device = resolve_device(args.video_device)
        args.head_device = resolve_device(args.head_device)
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"Devices: video encoder = {args.video_device}, prediction head = {args.head_device}")
    paths = [args.video] if args.video else sorted(
        p for p in (ROOT / "INPUT").glob("*.mp4") if not p.name.endswith(".tmp.mp4"))
    if not paths:
        print(f"No MP4 found. Drop a video into {ROOT / 'INPUT'} and run the analyze script again.")
        return 1
    failures = []
    for path in paths:
        try:
            analyze_one(path, args)
        except Exception as exc:
            failures.append((str(path), str(exc)))
            print(f"FAILED: {path}: {exc}", file=sys.stderr)
            low = str(exc).lower()
            if "out of memory" in low or "cuda oom" in low or "mps backend out of memory" in low:
                print("Memory tip: close GPU/memory-heavy apps and retry, or rerun with --video-device cpu. "
                      "On a Mac, TRIBE_MPS_PRECISION=fp16 (default) uses the least memory.", file=sys.stderr)
    if failures:
        print(f"{len(failures)} video(s) failed. See errors above; cached stages remain reusable.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
