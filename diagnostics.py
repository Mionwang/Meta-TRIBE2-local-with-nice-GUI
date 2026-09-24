"""Show local model runtime readiness without downloading weights."""
import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
print("Project:", root)
print("System:", platform.system(), platform.machine(), platform.mac_ver()[0] or platform.release())
print("Python:", sys.version.split()[0])
print("Free disk: %.1f GB" % (shutil.disk_usage(root).free / 1e9))
for name in ("torch", "torchvision", "tribev2", "neuralset", "transformers", "mne", "imageio_ffmpeg", "flask"):
    print(f"{name}: {'installed' if importlib.util.find_spec(name) else 'MISSING'}")
accelerator = "CPU only (slow)"
try:
    import torch
    print("PyTorch:", torch.__version__)
    print("CUDA available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        accelerator = "NVIDIA CUDA"
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            free, total = torch.cuda.mem_get_info(index)
            print(f"GPU {index}: {props.name}; total {total / 2**30:.2f} GiB; free {free / 2**30:.2f} GiB")
    mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    print("Apple MPS available:", mps)
    if mps and not torch.cuda.is_available():
        accelerator = "Apple Silicon (Metal / MPS)"
        try:
            memsize = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
            print(f"Unified memory: {memsize / 2**30:.0f} GiB" + ("  (16 GiB+ recommended)" if memsize < 15 * 2**30 else ""))
        except Exception:
            pass
except Exception as exc:
    print("PyTorch check failed:", exc)
print("Accelerator that will be used:", accelerator)
try:
    import imageio_ffmpeg
    print("Bundled FFmpeg:", imageio_ffmpeg.get_ffmpeg_exe())
except Exception as exc:
    print("FFmpeg check failed:", exc)
if shutil.which("nvidia-smi"):
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=15)
        print("NVIDIA driver:", result.stdout.strip() if result.returncode == 0 else result.stderr.strip())
    except Exception as exc:
        print("NVIDIA driver query failed:", exc)
if sys.platform == "darwin":
    print("Text-to-speech (say):", "available" if shutil.which("say") else "MISSING")
