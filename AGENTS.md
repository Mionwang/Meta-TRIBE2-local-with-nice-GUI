# AGENTS.md — setting up TRIBE Response Lab

Instructions for a coding agent (or a person) installing this repo on a new machine. Follow the steps in order and check each one before moving on.

## What this repo is

A local Windows app that runs Meta's **TRIBE v2** brain-response model (`facebook/tribev2`) on a video, audio clip, image or text. It turns the predicted cortical activity into experimental timeline curves (an attention proxy, sensory, cognitive and so on). It has:

- `gui.py` + `web/` — a Flask server and a browser UI at `http://127.0.0.1:7860`
- `analyze.py` — the command-line runner (the GUI starts it in a subprocess)
- `src/` — input conversion (`prepare_input.py`), ROI metrics and reports (`reel_metrics.py`), a V-JEPA2 bf16 patch for the GPU (`gpu_video.py`), and the Windows text-to-speech helper (`speak_text.ps1`)

The repo **does not include** the TRIBE source, model weights, the Python environment, or anyone's inputs and results. `setup.ps1` fetches or creates all of these.

## Hard requirements

| Requirement | Why | How to check |
| --- | --- | --- |
| **Windows 10/11** | `.bat` launchers, `speak_text.ps1` uses Windows SAPI, paths assume Windows | — |
| **NVIDIA GPU, 8 GB+ VRAM**, recent driver (CUDA 12.4 compatible) | PyTorch is installed from the `cu124` wheel index; V-JEPA2 runs in bf16 on CUDA; RTX 30-series or newer recommended (native bf16) | `nvidia-smi` |
| **Python 3.12** (64-bit) | The venv is built with 3.12; the pinned packages target it | `py -3.12 --version` |
| **Git** | `setup.ps1` clones `facebookresearch/tribev2` at a pinned commit | `git --version` |
| **~25 GB free disk** | venv (~6 GB with CUDA torch) + model weights and feature caches in `cache/` | — |
| **Internet on first run** | pip installs, the TRIBE clone, Hugging Face weight downloads, the HCP-MMP1 atlas files | — |

No Hugging Face login is needed for the default path. Only the optional `--with-language` CLI flag needs gated access to `meta-llama/Llama-3.2-3B` (`huggingface-cli login`).

FFmpeg does **not** need a separate install. It comes bundled with the `imageio-ffmpeg` pip package.

## Setup steps

Run these from the repo root in PowerShell.

1. **Check the prerequisites** listed above. If `py -3.12` is missing, install Python 3.12 from python.org (tick "Add python.exe to PATH" and keep the `py` launcher). If there's no NVIDIA GPU, stop and tell the user: the GPU path won't work, and the CPU fallback (`--video-device cpu --head-device cpu`, CLI only) is very slow.

2. **Run the installer:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```
   If Python 3.12 isn't on the `py` launcher, run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Python "C:\Path\To\Python312\python.exe"
   ```
   The script:
   - creates `.venv\` with Python 3.12
   - clones `https://github.com/facebookresearch/tribev2` into `vendor\tribev2` and checks out commit `af58661791a351a448a489042a28f6c37e1c14b7`
   - installs `torch==2.6.0` and `torchvision==0.21.0` from `https://download.pytorch.org/whl/cu124`
   - runs `pip install -e vendor\tribev2 -r requirements-local.txt` (Flask, transformers, mne, scipy, matplotlib, imageio-ffmpeg, nibabel, requests and others)
   - runs `diagnostics.py`

3. **Check the diagnostics output.** The last lines must show:
   - every package listed as `installed` (no `MISSING`)
   - `PyTorch: 2.6.0+cu124`
   - `CUDA available: True`, plus a GPU line with its VRAM

   You can rerun the check at any time with `.\diagnostics.bat`.

4. **Smoke test** (this downloads several GB of weights the first time, so allow 5–20 minutes):
   ```powershell
   .\analyze.bat SAMPLE\test_reel.mp4
   ```
   The run passes if it prints `Done: ...\OUTPUT\test_reel` and `OUTPUT\test_reel\` contains `metrics.json`, `attention_timeline.csv`, `attention_plot.png` and `report.html`. The GUI shows this result as "Demo · test_reel.mp4".

5. **Launch the app:** double-click `start_gui.bat`, or run `.\.venv\Scripts\python.exe gui.py`. A browser tab opens at `http://127.0.0.1:7860`. If that port is taken, the app uses the next free one and prints it. Keep the console window open while using the app.

## If something fails

| Symptom | Fix |
| --- | --- |
| `CUDA available: False` | The driver is too old, or a CPU-only torch got installed. Run `.venv\Scripts\python.exe -m pip install --force-reinstall --index-url https://download.pytorch.org/whl/cu124 torch==2.6.0 torchvision==0.21.0` |
| `This GPU/PyTorch build does not support CUDA bf16` | The GPU/torch build lacks bf16. Use the CLI with `--video-device cpu` |
| CUDA out of memory | Close other GPU apps (games, other AI tools) and retry. Or use `--video-device cpu` (slower) |
| Hugging Face download errors or 401 | Check your internet connection. Models go to `cache\models`, and `HF_HOME` is set there automatically. The default models are public |
| Atlas download fails (`HCP-MMP1`) | `reel_metrics.py` downloads two `.annot` files from figshare/S3 and checks their MD5. Retry on a stable connection |
| Text input fails | Needs Windows PowerShell and an installed English SAPI voice (Settings → Time & language → Speech) |
| `ModuleNotFoundError: flask` | Rerun `setup.ps1`, or `.venv\Scripts\python.exe -m pip install -r requirements-local.txt` |

`requirements-lock.txt` is a reference `pip freeze` from a working machine (Python 3.12, RTX 4060, CUDA 12.4). Use it to compare versions when debugging. Don't install from it directly: it pins the `+cu124` torch builds, which need the PyTorch index URL.

## Layout after setup

```
.venv/            Python env                       (git-ignored)
vendor/tribev2/   official TRIBE v2 source, pinned (git-ignored)
cache/            model weights, features, atlas   (git-ignored, many GB)
INPUT/            copies of analyzed inputs        (git-ignored)
OUTPUT/<id>/      per-input results                (git-ignored)
```

## Rules for agents working in this repo

- Don't commit `.venv/`, `vendor/`, `cache/`, `INPUT/` or `OUTPUT/`. `.gitignore` already excludes them.
- Don't edit files under `vendor/tribev2`. The local changes are applied at runtime instead (`src/gpu_video.py`, and the YAML/Hub-path workarounds in `analyze.py`).
- If you change `MODEL_REVISION` in `analyze.py` or the pinned commit in `setup.ps1`, say so clearly. Cached predictions are keyed on the model revision.
- The outputs are **experimental neural proxies**, ranked within one input. Don't present them as real retention, attention or virality predictions in UI text or docs.

## Licensing

- TRIBE v2 code and weights: **CC BY-NC 4.0**, non-commercial use only. See `TRIBE-LICENSE.txt`.
- The ROI parcel groups are adapted from Apache-2.0 code. See `ANALYSIS-APACHE-LICENSE.txt` and `NOTICE.md`.
