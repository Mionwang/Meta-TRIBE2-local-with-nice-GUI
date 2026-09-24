"""Show local model runtime readiness without downloading weights."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
print("Project:", root)
print("Python:", sys.version.split()[0])
print("Free disk: %.1f GB" % (shutil.disk_usage(root).free / 1e9))
for name in ("torch", "torchvision", "tribev2", "neuralset", "transformers", "mne", "imageio_ffmpeg"):
    print(f"{name}: {'installed' if importlib.util.find_spec(name) else 'MISSING'}")
try:
    import torch
    print("PyTorch:", torch.__version__)
    print("CUDA available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            free, total = torch.cuda.mem_get_info(index)
            print(f"GPU {index}: {props.name}; total {total / 2**30:.2f} GiB; free {free / 2**30:.2f} GiB")
except Exception as exc:
    print("PyTorch check failed:", exc)
try:
    import imageio_ffmpeg
    print("Bundled FFmpeg:", imageio_ffmpeg.get_ffmpeg_exe())
except Exception as exc:
    print("FFmpeg check failed:", exc)
try:
    result = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                            capture_output=True, text=True, timeout=15)
    print("NVIDIA driver:", result.stdout.strip() if result.returncode == 0 else result.stderr.strip())
except Exception as exc:
    print("NVIDIA driver query failed:", exc)
