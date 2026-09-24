# AGENTS.md: setting up TRIBE Response Lab

Instructions for a coding agent (or a person) installing this repo. First work out which platform you're on, then follow **only** that section. Check each step before moving on.

## What this repo is

This is a local app that runs Meta's **TRIBE v2** brain-response model (`facebook/tribev2`) on a video, audio clip, image or text. It turns the predicted cortical activity into experimental timeline curves and a toy "projected performance" estimate.

| Path | What it is |
| --- | --- |
| `gui.py` + `web/` | Flask server and browser UI at `http://127.0.0.1:7860` |
| `analyze.py` | Command-line runner (the GUI runs it in a subprocess). Picks the device automatically: CUDA, then MPS, then CPU |
| `src/prepare_input.py` | Converts inputs; text-to-speech via Windows SAPI or macOS `say` |
| `src/gpu_video.py` | NVIDIA only: runs V-JEPA2 in bf16 |
| `src/apple_silicon.py` | Apple Silicon only: moves the encoders onto the Metal GPU (MPS) at runtime |
| `src/reel_metrics.py`, `src/projection.py` | ROI metrics, reports, toy projections |

The repo **does not include** the TRIBE source, the model weights, the Python environment, or anyone's inputs and results. The setup script fetches or creates all of these.

## Pick your platform

| Platform | Supported? | Install script |
| --- | --- | --- |
| Windows 10/11 with an NVIDIA GPU (8 GB+ VRAM) | Yes (tested on RTX 4060) | `setup.ps1` |
| macOS on Apple Silicon (M1/M2/M3/M4…), 16 GB+ unified memory recommended | Yes, **experimental / less tested** | `setup.sh` |
| Intel Mac | **No**. PyTorch 2.6 has no Intel-Mac builds | — |
| Windows without an NVIDIA GPU, or Linux | CPU only, very slow; not officially supported | — |

Check with `uname -m` on macOS (it must print `arm64`), or `nvidia-smi` on Windows.

Both platforms need about 25 GB of free disk and internet access on the first run (pip packages, the TRIBE source, Hugging Face weights, the HCP-MMP1 atlas). No Hugging Face login is needed for the default path. FFmpeg comes bundled through the `imageio-ffmpeg` package.

---

## Windows setup (NVIDIA)

1. **Prerequisites:**
   - **Python 3.12, 64-bit:** check with `py -3.12 --version`. If it's missing, install it from python.org and keep the `py` launcher.
   - **Git:** check with `git --version`.
   - **An NVIDIA driver that supports CUDA 12.4:** check with `nvidia-smi`.
2. **Install:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   # if Python 3.12 isn't on the py launcher:
   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Python "C:\Path\To\Python312\python.exe"
   ```
   This does the following:
   - creates `.venv\`
   - clones `facebookresearch/tribev2` at commit `af58661791a351a448a489042a28f6c37e1c14b7` into `vendor\tribev2`
   - installs `torch==2.6.0` and `torchvision==0.21.0` from `https://download.pytorch.org/whl/cu124`
   - installs `vendor\tribev2` and `requirements-local.txt`
   - runs the diagnostics
3. **Check the diagnostics output:** there should be no `MISSING` lines, `PyTorch: 2.6.0+cu124`, `CUDA available: True` and `Accelerator that will be used: NVIDIA CUDA`. To rerun the check, use `.\diagnostics.bat`.
4. **Smoke test:** run `.\analyze.bat SAMPLE\test_reel.mp4`. It passes when it prints `Done: ...\OUTPUT\test_reel`. The first run downloads several GB of model weights and can take 5–20 minutes.
5. **Launch:** double-click `start_gui.bat`.

## macOS setup (Apple Silicon)

1. **Prerequisites:**
   - **Git:** check with `git --version`. If it's missing, run `xcode-select --install`.
   - **Python 3.12:** check with `python3.12 --version`. If it's missing, run `brew install python@3.12` (or use the python.org installer).
   - **Apple Silicon:** `uname -m` must print `arm64`.
2. **Install**, from the repo root in Terminal:
   ```bash
   bash setup.sh
   # or point it at a specific interpreter:
   PYTHON=/opt/homebrew/bin/python3.12 bash setup.sh
   ```
   This does the following:
   - creates `.venv/`
   - clones `facebookresearch/tribev2` at the same pinned commit into `vendor/tribev2`
   - installs `torch==2.6.0` and `torchvision==0.21.0` from standard PyPI (the arm64 wheels include Metal/MPS)
   - installs `vendor/tribev2` and `requirements-local.txt`
   - makes the `.command` launchers executable and clears Gatekeeper quarantine flags
   - runs the diagnostics

   Use `bash setup.sh`, not `./setup.sh`. Web uploads and zip downloads can strip the executable bit.
3. **Check the diagnostics output:** there should be no `MISSING` lines, `Apple MPS available: True`, `Accelerator that will be used: Apple Silicon (Metal / MPS)` and `Text-to-speech (say): available`. To rerun the check, use `./diagnostics.command`.
4. **Smoke test:** run `./analyze.command SAMPLE/test_reel.mp4`. It passes when it prints `Devices: video encoder = mps ...` and then `Done: .../OUTPUT/test_reel`.
5. **Launch:** double-click `start_gui.command` in Finder, or run `./start_gui.command`. If macOS blocks it the first time, right-click it and choose **Open**.

**How the Apple Silicon path works.** neuralset's config only accepts `cpu`, `cuda` or `auto` as a device. So `analyze.py` passes `cpu` in the config, and `src/apple_silicon.py` moves the V-JEPA2 and Wav2Vec-BERT encoders onto `mps` at runtime:

- **V-JEPA2** runs under float16 autocast. If a clip ever produces NaN or inf, that clip is recomputed in float32 and the model stays in float32.
- **Settings:** `TRIBE_MPS_PRECISION=fp32` forces float32 throughout. `PYTORCH_ENABLE_MPS_FALLBACK=1` is set automatically, so operations Metal doesn't support run on the CPU instead.
- **Prediction head:** it tries `mps` first and falls back to CPU if Metal fails on it.
- **Caches:** cached features are keyed without the device, so they work across machines.

## If something fails

| Symptom | Fix |
| --- | --- |
| `CUDA available: False` (Windows) | The driver is too old, or a CPU-only torch got installed. Run `.venv\Scripts\python.exe -m pip install --force-reinstall --index-url https://download.pytorch.org/whl/cu124 torch==2.6.0 torchvision==0.21.0` |
| `Apple MPS available: False` (Mac) | You're on an Intel Mac, an x86 Python running under Rosetta, or macOS older than 12.3. `python3.12 -c "import platform;print(platform.machine())"` must print `arm64` |
| `MPS backend out of memory` | Close memory-heavy apps and retry. 8 GB Macs will struggle. Last resort: `./analyze.command file.mp4 --video-device cpu` (slow) |
| Mac results look wrong or contain NaNs | Rerun with `TRIBE_MPS_PRECISION=fp32 ./analyze.command file.mp4 --force` |
| CUDA out of memory (Windows) | Close other GPU apps, or use `--video-device cpu` (slow) |
| Hugging Face download errors | Check your internet connection. Weights go to `cache/models` (`HF_HOME` is set automatically). The default models are public |
| Atlas download fails (`HCP-MMP1`) | Retry on a stable connection. The two `.annot` files are MD5-verified |
| Text input fails | Windows needs PowerShell and an English SAPI voice. On macOS, check that `say "hello"` works |
| `permission denied: ./start_gui.command` | Run `chmod +x *.command`, or just `bash setup.sh` again |

`requirements-lock.txt` is a reference `pip freeze` from a working Windows/CUDA machine. Use it to compare versions when debugging, but don't install from it directly.

## Layout after setup

```
.venv/            Python env                       (git-ignored)
vendor/tribev2/   official TRIBE v2 source, pinned (git-ignored)
cache/            model weights, features, atlas   (git-ignored, many GB)
INPUT/            copies of analyzed inputs        (git-ignored)
OUTPUT/<id>/      per-input results                (git-ignored)
```

## Rules for agents working in this repo

- Don't commit `.venv/`, `vendor/`, `cache/`, `INPUT/` or `OUTPUT/`.
- Don't edit files under `vendor/tribev2` or installed packages. Platform fixes are applied at runtime in `src/gpu_video.py`, `src/apple_silicon.py` and `analyze.py`.
- Keep `*.sh` and `*.command` files with LF line endings (`.gitattributes` enforces this).
- If you change `MODEL_REVISION` in `analyze.py` or the pinned commit in the setup scripts, say so clearly. Cached predictions are keyed on the model revision and the device.
- The outputs are **experimental neural proxies**, and the projections are a toy. Don't present them as real retention, attention or virality predictions.

## Licensing

- TRIBE v2 code and weights: **CC BY-NC 4.0**, non-commercial use only. See `TRIBE-LICENSE.txt`.
- The ROI parcel groups are adapted from Apache-2.0 code. See `ANALYSIS-APACHE-LICENSE.txt` and `NOTICE.md`.
