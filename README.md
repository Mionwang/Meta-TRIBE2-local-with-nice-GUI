# Local TRIBE v2 Reel attention analysis

> **First time here?** See [`AGENTS.md`](AGENTS.md) for requirements and setup (written so a coding agent can follow it step by step).

This folder runs Meta's official TRIBE v2 brain-response model on video or audio and turns its fsaverage5 cortical predictions into **experimental, within-input review cues**. It does not predict an actual viewer's attention, Instagram retention, or virality.

## Quick use

1. Double-click `start_gui.bat`. Keep its small command window open while using the app.
2. In the browser page that opens, drag in a video, audio, image, or `.txt` file; click **browse**; or switch to the **Text** tab and paste a script.
3. Watch the progress steps while the local model works (you can **Cancel** at any time). The page then shows the source preview, interactive response graphs, and download buttons.

The page runs only on this computer at `http://127.0.0.1:7860` (or the next free port). Inputs are stored in `INPUT`; completed analyses are stored in `OUTPUT`. Results remain available in the searchable **Library** when you reopen the app. Files up to 1 GB are accepted. First-time model downloads and encoding can take several minutes; subsequent runs reuse cached weights and features.

Supported input paths, using only components already installed on this PC:

| Input | Browser formats | How it is analyzed |
| --- | --- | --- |
| Video | MP4, MOV, MKV, WebM, AVI | TRIBE video and audio; non-MP4 formats are converted to MP4 locally. |
| Audio | WAV, MP3, FLAC, OGG, M4A | Native audio-only TRIBE path; M4A is converted to WAV locally. |
| Image | PNG, JPG, WebP, BMP | Held as a static, silent six-second video for TRIBE's visual path. The resulting timeline is an artificial hold, not motion in the image. |
| Text | Pasted text or UTF-8 TXT | Read aloud with Windows' installed English voice, then sent through the audio-only path. This is not the gated TRIBE language encoder. |

No additional model packages are installed for these adapters. Relative 0–100 curves describe variation *within one input*; they are not comparable retention or virality percentages. Static-image results omit temporal editing observations.

To use the command-line workflow instead, put `.mp4` files in `INPUT`, double-click `analyze.bat` (or drag an MP4 onto it), and open `OUTPUT\<video name>\report.html`.

The first run downloads large public model weights into `cache\models` and prepares feature caches in `cache\features`. Later runs reuse unchanged cortical predictions and feature caches. Keep the `cache` folder if you want to avoid downloads and repeated encoding.

Outputs per MP4:

- `attention_timeline.csv`: 1-second ROI-derived curves, raw ROI means, z-scores, and within-clip display indices.
- `metrics.json`: hook, sustained attention, volatility, weak sections, peaks, recoveries, method, and provenance.
- `attention_plot.png` and `report.html`: reviewable timeline and editing observations.
- `cortical_activity.npz`: compressed official model predictions and times for later calibration.

## Commands

From PowerShell in this folder:

```powershell
.\diagnostics.bat
.\analyze.bat
.\analyze.bat "E:\path\to\my_reel.mp4"
.\.venv\Scripts\python.exe .\analyze.py "INPUT\my_reel.mp4" --no-audio
```

The `--no-audio` option is for a silent MP4 or deliberate video-only analysis. The default includes video and audio, but skips speech-to-text and the gated Llama text encoder. `--with-language` enables the official full path, which requires Hugging Face CLI access to `meta-llama/Llama-3.2-3B`; this path is experimental and can exceed 8 GB VRAM. Browser login alone does not provide a CLI token. CUDA V-JEPA2 uses bf16 weights and activations to fit this RTX 4060; `--video-device cpu` is the slower fallback if GPU memory is occupied. `--force` recomputes cortical predictions, while upstream feature caches can still be reused.

## Setup or repair

The environment is installed in `.venv` using Python 3.12 and CUDA PyTorch 2.6.0. If you need to recreate it, run `powershell -ExecutionPolicy Bypass -File .\setup.ps1`. It installs the pinned official TRIBE v2 source in `vendor\tribev2`, pinned CUDA PyTorch, and the local requirements. `requirements-lock.txt` records exact installed versions. No paid GPU or online inference service is used; public weight downloads are the only network need after installation.

## How it works

The official TRIBE data loader extracts features sequentially and releases each encoder after its features are cached. The local runner keeps the TRIBE prediction model on CPU during that extraction, then moves it to CUDA for inference. A local precision patch runs the original V-JEPA2 backbone in bf16 on CUDA, then casts features back to float32 before aggregation and caching. The four-second sample encoded at about 2.3 seconds per step on this RTX 4060; the unmodified float32 CPU route took about 57 seconds per step. Audio uses the GPU if available. The inference batch size and Windows worker count are conservative.

The ROI mapping adapts the open-source [TRIBE v2 Video Brain-Score analysis](https://huggingface.co/spaces/techfreakworm/tribev2-brain-timeline). It uses the HCP-MMP1 annotations and reproduces Meta's fsaverage5 vertex selection, with atlas file hashes verified against MNE. Orienting, sustained, and cognitive curves remain separate. Their weighted combination is an **attention proxy**, not a validated physiological measure of attention. The displayed 0–100 values are rank positions *within the same clip*. They cannot be compared as calibrated performance percentages across Reels. The first three seconds form the hook index; later seconds form the sustained index. Weak sections are the clip's lowest quartile. TRIBE's one-second fMRI prediction resolution does not support sub-second edit timestamps.

TRIBE is trained for predicted cortical activity, and its output compensates for the approximate BOLD hemodynamic delay. There is no Instagram retention calibration here. Save real 1-second/3-second hold, average watch time, completion, rewatches, and shares separately before fitting or judging a predictive relationship.

## License and sources

- [Meta TRIBE v2 source](https://github.com/facebookresearch/tribev2), commit `af58661791a351a448a489042a28f6c37e1c14b7`.
- [Official model](https://huggingface.co/facebook/tribev2), pinned revision `f894e783020944dcd96e5568550afe2aa9743f9f`: CC BY-NC 4.0; personal, non-commercial research use.
- [Reference ROI/metrics source](https://huggingface.co/spaces/techfreakworm/tribev2-brain-timeline), commit `56e31aa6364c989a1c5a58620db110434f7851aa`, Apache 2.0. See `ANALYSIS-APACHE-LICENSE.txt`.

See `NOTICE.md` for limitations and provenance.
