# Local TRIBE v2 Reel attention analysis

> **First time here?** See [`AGENTS.md`](AGENTS.md) for requirements and setup (written so a coding agent can follow it step by step).

This folder runs Meta's official TRIBE v2 brain-response model on video or audio and turns its fsaverage5 cortical predictions into **experimental, within-input review cues**. It does not predict an actual viewer's attention, Instagram retention, or virality.

## Platforms

| | Windows 10/11 | macOS (Apple Silicon, M1 or newer) |
| --- | --- | --- |
| Accelerator | NVIDIA GPU, 8 GB+ VRAM (CUDA, bf16) | Apple GPU via Metal / MPS (fp16 autocast), 16 GB+ unified memory recommended |
| Install | `powershell -ExecutionPolicy Bypass -File .\setup.ps1` | `bash setup.sh` |
| Start the app | double-click `start_gui.bat` | double-click `start_gui.command` |
| Command line | `analyze.bat`, `diagnostics.bat` | `./analyze.command`, `./diagnostics.command` |
| Text-to-speech | Windows SAPI voice | macOS `say` |

The Apple Silicon path is **experimental**: it was written for this release but has not been benchmarked yet. Intel Macs are not supported (no PyTorch 2.6 builds). Devices are picked automatically (NVIDIA CUDA → Apple MPS → CPU); override with `--video-device cuda|mps|cpu`.

## Quick use

1. Double-click `start_gui.bat` (Windows) or `start_gui.command` (macOS). Keep its small terminal window open while using the app.
2. In the browser page that opens, drag in a video, audio, image, or `.txt` file; click **browse**; or switch to the **Text** tab and paste a script.
3. Watch the progress steps while the local model works (you can **Cancel** at any time). The page then shows the source preview, interactive response graphs, and download buttons.

The page runs only on this computer at `http://127.0.0.1:7860` (or the next free port). Inputs are stored in `INPUT`; completed analyses are stored in `OUTPUT`. Results remain available in the searchable **Library** when you reopen the app. Files up to 1 GB are accepted. First-time model downloads and encoding can take several minutes; subsequent runs reuse cached weights and features.

Supported input paths, using only components already installed on this PC:

| Input | Browser formats | How it is analyzed |
| --- | --- | --- |
| Video | MP4, MOV, MKV, WebM, AVI | TRIBE video and audio; non-MP4 formats are converted to MP4 locally. |
| Audio | WAV, MP3, FLAC, OGG, M4A | Native audio-only TRIBE path; M4A is converted to WAV locally. |
| Image | PNG, JPG, WebP, BMP | Held as a static, silent six-second video for TRIBE's visual path. The resulting timeline is an artificial hold, not motion in the image. |
| Text | Pasted text or UTF-8 TXT | Read aloud with the system's English voice (Windows SAPI or macOS `say`), then sent through the audio-only path. This is not the gated TRIBE language encoder. |

No additional model packages are installed for these adapters. Relative 0–100 curves describe variation *within one input*; they are not comparable retention or virality percentages. Static-image results omit temporal editing observations.

To use the command-line workflow instead, put `.mp4` files in `INPUT`, double-click `analyze.bat` / `analyze.command` (or pass an MP4 path), and open `OUTPUT/<video name>/report.html`.

The first run downloads large public model weights into `cache\models` and prepares feature caches in `cache\features`. Later runs reuse unchanged cortical predictions and feature caches. Keep the `cache` folder if you want to avoid downloads and repeated encoding.

Outputs per MP4:

- `attention_timeline.csv`: 1-second ROI-derived curves, raw ROI means, z-scores, and within-clip display indices.
- `metrics.json`: hook, sustained attention, volatility, weak sections, peaks, recoveries, method, and provenance.
- `attention_plot.png` and `report.html`: reviewable timeline and editing observations.
- `cortical_activity.npz`: compressed official model predictions and times for later calibration.

## Projected performance (toy estimate)

Each analysis also shows projected views, likes and comments. This is an experiment for fun, **not a forecast**:

- `src/projection.py` builds a 0–100 *response score* from TRIBE's raw (cross-clip comparable) ROI activity: opening pull, hold, value-region response, sensory intensity and variation. As your library grows, factors are partly ranked against your own past analyses.
- `projectCounts()` in `web/app.js` turns that score into numbers using **your typical views** (editable in the card): score 50 = your typical, 0 = 0.2×, 100 = 5×; likes are 2.5–7.5 % of views, comments 1–6 % of likes. Ranges are ÷3 to ×3.
- None of these weights are fitted to real Instagram data. The model does not see captions, hashtags, trends, posting time, follower count or calls to action. Edit the numbers freely.

## Commands

From PowerShell in this folder:

```powershell
# Windows (PowerShell)
.\diagnostics.bat
.\analyze.bat
.\analyze.bat "E:\path\to\my_reel.mp4"

# macOS (Terminal)
./diagnostics.command
./analyze.command ~/Movies/my_reel.mp4
./analyze.command ~/Movies/my_reel.mp4 --video-device cpu   # if the Metal path misbehaves
.\.venv\Scripts\python.exe .\analyze.py "INPUT\my_reel.mp4" --no-audio
```

The `--no-audio` option is for a silent MP4 or deliberate video-only analysis. The default includes video and audio, but skips speech-to-text and the gated Llama text encoder. `--with-language` enables the official full path, which requires Hugging Face CLI access to `meta-llama/Llama-3.2-3B`; this path is experimental and can exceed 8 GB VRAM. Browser login alone does not provide a CLI token. On NVIDIA, V-JEPA2 uses bf16 weights and activations to fit an 8 GB card. On Apple Silicon it runs on the Metal GPU under float16 autocast and automatically redoes a clip in float32 if half precision overflows (`TRIBE_MPS_PRECISION=fp32` forces float32). `--video-device cpu` is the slow fallback on either platform. `--force` recomputes cortical predictions, while upstream feature caches can still be reused.

## Setup or repair

The environment is installed in `.venv` using Python 3.12 and PyTorch 2.6.0 (CUDA 12.4 build on Windows, the standard Metal-enabled build on macOS). To create or recreate it, run `powershell -ExecutionPolicy Bypass -File .\setup.ps1` on Windows or `bash setup.sh` on macOS. Both install the pinned official TRIBE v2 source in `vendor/tribev2`, PyTorch, and the local requirements. See [`AGENTS.md`](AGENTS.md) for the full checklist. `requirements-lock.txt` records exact installed versions. No paid GPU or online inference service is used; public weight downloads are the only network need after installation.

## How it works

The official TRIBE data loader extracts features sequentially and releases each encoder after its features are cached. The local runner keeps the TRIBE prediction model on CPU during that extraction, then moves it to CUDA for inference. A local precision patch runs the original V-JEPA2 backbone in bf16 on CUDA, then casts features back to float32 before aggregation and caching. The four-second sample encoded at about 2.3 seconds per step on this RTX 4060; the unmodified float32 CPU route took about 57 seconds per step. Audio uses the GPU if available. On Apple Silicon, `src/apple_silicon.py` moves the V-JEPA2 and Wav2Vec-BERT encoders onto the Metal GPU at runtime (neuralset's config only knows cpu/cuda), and the small prediction head falls back to CPU if Metal lacks an operation. The inference batch size and worker count are conservative.

The ROI mapping adapts the open-source [TRIBE v2 Video Brain-Score analysis](https://huggingface.co/spaces/techfreakworm/tribev2-brain-timeline). It uses the HCP-MMP1 annotations and reproduces Meta's fsaverage5 vertex selection, with atlas file hashes verified against MNE. Orienting, sustained, and cognitive curves remain separate. Their weighted combination is an **attention proxy**, not a validated physiological measure of attention. The displayed 0–100 values are rank positions *within the same clip*. They cannot be compared as calibrated performance percentages across Reels. The first three seconds form the hook index; later seconds form the sustained index. Weak sections are the clip's lowest quartile. TRIBE's one-second fMRI prediction resolution does not support sub-second edit timestamps.

TRIBE is trained for predicted cortical activity, and its output compensates for the approximate BOLD hemodynamic delay. There is no Instagram retention calibration here. Save real 1-second/3-second hold, average watch time, completion, rewatches, and shares separately before fitting or judging a predictive relationship.

## License and sources

- [Meta TRIBE v2 source](https://github.com/facebookresearch/tribev2), commit `af58661791a351a448a489042a28f6c37e1c14b7`.
- [Official model](https://huggingface.co/facebook/tribev2), pinned revision `f894e783020944dcd96e5568550afe2aa9743f9f`: CC BY-NC 4.0; personal, non-commercial research use.
- [Reference ROI/metrics source](https://huggingface.co/spaces/techfreakworm/tribev2-brain-timeline), commit `56e31aa6364c989a1c5a58620db110434f7851aa`, Apache 2.0. See `ANALYSIS-APACHE-LICENSE.txt`.

See `NOTICE.md` for limitations and provenance.
