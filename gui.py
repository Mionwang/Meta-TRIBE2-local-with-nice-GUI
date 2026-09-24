"""Local browser UI for the existing TRIBE v2 command-line pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from prepare_input import kind_for_suffix, prepare_input

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
INPUT = ROOT / "INPUT"
OUTPUT = ROOT / "OUTPUT"
JOBS: dict[str, dict] = {}
PROCS: dict[str, subprocess.Popen] = {}
JOBS_LOCK = threading.Lock()
GPU_CACHE: dict = {"at": 0.0, "value": None}
WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tribe-analysis")
RESULT_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
FILES = {"attention_timeline.csv", "metrics.json", "attention_plot.png", "report.html", "cortical_activity.npz"}

app = Flask(__name__, static_folder=str(WEB), static_url_path="/static")


class _QuietPolling(logging.Filter):
    """Hide the browser's routine status/progress polls from the console log."""
    NOISY = re.compile(r'"GET /api/(status|jobs/[0-9a-f]+) HTTP/[\d.]+" 200')

    def filter(self, record: logging.LogRecord) -> bool:
        return not self.NOISY.search(record.getMessage())


logging.getLogger("werkzeug").addFilter(_QuietPolling())
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GiB local uploads


def _update(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        if JOBS[job_id].get("status") == "cancelled" and "status" not in fields:
            return  # late progress lines from a killed process
        JOBS[job_id].update(fields)


def _snapshot(job_id: str) -> dict | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def _stage_from_log(line: str) -> tuple[str, int] | None:
    low = line.lower()
    if "using cached cortical predictions" in low:
        return "Using saved model predictions", 88
    if "fetching" in low or "checkpoint" in low:
        return "Loading TRIBE v2", 12
    if "extract audio" in low or "extractor: audio" in low:
        return "Reading audio", 28
    if "extractor: video" in low or "encoding video" in low:
        match = re.search(r"encoding video:\s*(\d+)%", low)
        return "Encoding video", 38 + (round(int(match.group(1)) * 0.42) if match else 0)
    if "running tribe prediction" in low:
        return "Predicting cortical activity", 86
    if "done:" in low:
        return "Building your graphs", 96
    return None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _run_job(job_id: str, source_path: Path, kind: str, result_id: str, original_name: str) -> None:
    with JOBS_LOCK:
        if JOBS[job_id].get("status") == "cancelled":
            return
        JOBS[job_id].update(status="running", stage="Preparing analysis", progress=8,
                            started_ms=int(time.time() * 1000))
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TRIBE_SOURCE_KIND"] = kind
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        if kind in {"image", "text"} or source_path.suffix.lower() in {".mov", ".mkv", ".webm", ".avi", ".m4a"}:
            _update(job_id, stage="Preparing input locally", progress=11)
        analysis_path, extra_args, explanation = prepare_input(source_path, kind, INPUT / result_id)
        command = [sys.executable, "-u", str(ROOT / "analyze.py"), str(analysis_path), *extra_args]
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   errors="replace", bufsize=1, creationflags=flags)
        with JOBS_LOCK:
            PROCS[job_id] = process
            cancelled_early = JOBS[job_id].get("status") == "cancelled"
        if cancelled_early:
            process.kill()
        lines: list[str] = []
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            lines.append(line)
            lines = lines[-35:]
            stage = _stage_from_log(line)
            if stage:
                _update(job_id, stage=stage[0], progress=max(_snapshot(job_id)["progress"], stage[1]))
            _update(job_id, log=lines)
        code = process.wait()
        with JOBS_LOCK:
            PROCS.pop(job_id, None)
            was_cancelled = JOBS[job_id].get("status") == "cancelled"
        if was_cancelled:
            return
        result_dir = OUTPUT / result_id
        if code != 0 or not (result_dir / "metrics.json").is_file():
            detail = next((line for line in reversed(lines) if line.startswith("FAILED:")),
                          f"Analysis stopped with code {code}. Check the log below.")
            _update(job_id, status="error", stage="Analysis could not finish", error=detail,
                    finished=_now())
            return
        (result_dir / "source_name.json").write_text(json.dumps({
            "filename": original_name, "kind": kind, "source_file": source_path.name,
            "analysis_file": analysis_path.name, "explanation": explanation,
        }, ensure_ascii=False), encoding="utf-8")
        _update(job_id, status="done", stage="Complete", progress=100, result_id=result_id,
                finished=_now(), finished_ms=int(time.time() * 1000))
    except Exception as exc:
        with JOBS_LOCK:
            PROCS.pop(job_id, None)
            if JOBS[job_id].get("status") == "cancelled":
                return
        _update(job_id, status="error", stage="Analysis could not start", error=str(exc),
                finished=_now())


def _result_dir(result_id: str) -> Path:
    if not RESULT_ID.fullmatch(result_id) or result_id in {".", ".."}:
        abort(404)
    path = OUTPUT / result_id
    if not path.is_dir():
        abort(404)
    return path


def _source_info(folder: Path) -> dict:
    defaults = {"filename": f"{re.sub(r'-[0-9a-f]{12}$', '', folder.name)}.mp4",
                "kind": "video", "source_file": f"{folder.name}.mp4",
                "analysis_file": f"{folder.name}.mp4",
                "explanation": "Video and its audio were analyzed together."}
    try:
        info = json.loads((folder / "source_name.json").read_text(encoding="utf-8"))
        if isinstance(info, dict):
            # Older results only stored {"filename": ...}; fill in the rest so
            # previews and kind detection still work for them.
            merged = {**defaults, **{k: v for k, v in info.items() if isinstance(v, str) and v}}
            return merged
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass
    return defaults


def _source_name(folder: Path) -> str:
    return _source_info(folder)["filename"]


@app.before_request
def same_origin_only():
    # The server only listens on 127.0.0.1, but any website open in the browser
    # could still POST to it. Refuse state-changing requests from other origins.
    if request.method in {"POST", "DELETE"}:
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify(error="Cross-origin requests are not allowed."), 403
    return None


def _gpu_info() -> dict | None:
    now = time.time()
    if now - GPU_CACHE["at"] < 4:
        return GPU_CACHE["value"]
    value = None
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True,
                             timeout=3, creationflags=flags)
        if out.returncode == 0 and out.stdout.strip():
            name, used, total, util = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
            value = {"name": name.replace("NVIDIA ", "").replace("GeForce ", ""),
                     "mem_used_mb": int(float(used)), "mem_total_mb": int(float(total)),
                     "util": int(float(util))}
    except (OSError, ValueError, subprocess.SubprocessError):
        value = None
    GPU_CACHE.update(at=now, value=value)
    return value


@app.get("/api/status")
def status():
    with JOBS_LOCK:
        active = [j for j in JOBS.values() if j["status"] in {"queued", "running"}]
    return jsonify(gpu=_gpu_info(), active_jobs=len(active))


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            abort(404)
        if job["status"] not in {"queued", "running"}:
            return jsonify(error="This analysis already finished."), 409
        job.update(status="cancelled", stage="Cancelled", finished=_now())
        process = PROCS.get(job_id)
    if process and process.poll() is None:
        process.kill()
    return jsonify(ok=True)


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found."), 404
    return _error


@app.errorhandler(500)
def server_error(_error):
    return jsonify(error="The local server hit an unexpected error. Check the console window."), 500


@app.get("/")
def home():
    return send_from_directory(WEB, "index.html")


@app.post("/api/analyze")
def analyze_upload():
    upload = request.files.get("file") or request.files.get("video")
    typed_text = request.form.get("text", "").strip()
    if upload is None and not typed_text:
        return jsonify(error="Choose a file or paste some text first."), 400
    if upload is not None and not upload.filename:
        return jsonify(error="Choose a file first."), 400
    original_name = Path(upload.filename).name if upload is not None else "Pasted text.txt"
    suffix = Path(original_name).suffix.lower()
    kind = kind_for_suffix(suffix)
    if kind is None:
        return jsonify(error="Use video, audio, image, or plain text in a supported format."), 400
    if typed_text and upload is None and len(typed_text) > 10000:
        return jsonify(error="Text is limited to 10,000 characters per analysis."), 400
    if upload is not None and suffix == ".mp4":
        header = upload.stream.read(12)
        upload.stream.seek(0)
        if len(header) < 12 or header[4:8] != b"ftyp":
            return jsonify(error="This file does not appear to be a valid MP4."), 400
    name = secure_filename(Path(original_name).stem).replace(".", "_").strip("._-")[:56] or kind
    staging_dir = ROOT / "cache" / "uploads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    temp = staging_dir / f"{uuid.uuid4().hex}.upload"
    if upload is not None:
        upload.save(temp)
    else:
        temp.write_text(typed_text, encoding="utf-8")
    if temp.stat().st_size == 0:
        temp.unlink(missing_ok=True)
        return jsonify(error="The uploaded file is empty."), 400
    digest = hashlib.sha256()
    with temp.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    result_id = f"{name}-{kind}-{digest.hexdigest()[:12]}"
    INPUT.mkdir(exist_ok=True)
    source_path = INPUT / f"{result_id}{suffix}"
    if source_path.exists():
        temp.unlink()
    else:
        temp.replace(source_path)
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "name": original_name, "kind": kind, "status": "queued",
           "stage": "Waiting for the GPU", "progress": 5, "log": [], "error": None,
           "result_id": None, "created": datetime.now().isoformat(timespec="seconds"),
           "created_ms": int(time.time() * 1000)}
    with JOBS_LOCK:
        JOBS[job_id] = job
    WORKER.submit(_run_job, job_id, source_path, kind, result_id, original_name)
    return jsonify(job_id=job_id, result_id=result_id), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    job = _snapshot(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@app.get("/api/recent")
def recent():
    limit = 500 if request.args.get("all") else 8
    items = []
    if OUTPUT.is_dir():
        for folder in sorted(OUTPUT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not folder.is_dir() or not RESULT_ID.fullmatch(folder.name):
                continue
            path = folder / "metrics.json"
            if not path.is_file():
                continue
            try:
                metrics = json.loads(path.read_text(encoding="utf-8"))
                source = _source_info(folder)
                items.append({"id": folder.name, "name": source["filename"], "kind": source.get("kind", "video"),
                              "hook": metrics.get("hook_strength"),
                              "later": metrics.get("sustained_attention"),
                              "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes"),
                              "demo": folder.name == "test_reel"})
            except (ValueError, OSError):
                continue
            if len(items) >= limit:
                break
    return jsonify(items)


@app.get("/api/results/<result_id>")
def result_data(result_id: str):
    folder = _result_dir(result_id)
    try:
        metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
        with (folder / "attention_timeline.csv").open(encoding="utf-8", newline="") as stream:
            rows = [{key: float(value) for key, value in row.items() if key and value}
                    for row in csv.DictReader(stream)]
    except (FileNotFoundError, ValueError, KeyError):
        return jsonify(error="This result is incomplete."), 409
    source = _source_info(folder)
    kind = source.get("kind", "video")
    preview = f"/api/results/{result_id}/source"
    text_preview = None
    if kind == "text":
        text_file = INPUT / Path(source.get("source_file", "")).name
        if text_file.is_file():
            text_preview = text_file.read_text(encoding="utf-8-sig")[:3000]
    return jsonify(id=result_id, name=source["filename"], kind=kind, metrics=metrics,
                   timeline=rows, explanation=source.get("explanation", ""),
                   preview_url=preview, text_preview=text_preview,
                   speech_url=f"/api/results/{result_id}/speech" if kind == "text" else None,
                   files={name: f"/api/results/{result_id}/files/{name}" for name in FILES
                          if (folder / name).is_file()})


@app.get("/api/results/<result_id>/files/<filename>")
def result_file(result_id: str, filename: str):
    folder = _result_dir(result_id)
    if filename not in FILES:
        abort(404)
    return send_from_directory(folder, filename, as_attachment=filename != "report.html", conditional=True)


@app.get("/api/results/<result_id>/source")
@app.get("/api/results/<result_id>/video")
def result_source(result_id: str):
    folder = _result_dir(result_id)
    if result_id == "test_reel":
        return send_from_directory(ROOT / "SAMPLE", "test_reel.mp4", conditional=True)
    source = _source_info(folder)
    name = source.get("source_file", "")
    if not name or Path(name).name != name:
        abort(404)
    if source.get("kind") == "video" and Path(name).suffix.lower() != ".mp4":
        name = source.get("analysis_file", name)
    path = INPUT / name
    if not path.is_file():
        abort(404)
    return send_from_directory(INPUT, path.name, conditional=True)


@app.get("/api/results/<result_id>/speech")
def result_speech(result_id: str):
    source = _source_info(_result_dir(result_id))
    if source.get("kind") != "text":
        abort(404)
    name = source.get("analysis_file", "")
    if not name or Path(name).name != name or Path(name).suffix.lower() != ".wav":
        abort(404)
    return send_from_directory(INPUT, name, conditional=True)


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return jsonify(error="The file is larger than 1 GB. Try a shorter or compressed export."), 413


def available_port(preferred: int) -> int:
    for port in range(preferred, preferred + 10):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Could not find a free local port. Close another TRIBE window and try again.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the local TRIBE v2 browser interface")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    port = available_port(args.port)
    url = f"http://127.0.0.1:{port}"
    print(f"TRIBE Response Lab is ready at {url}")
    print("Keep this window open while using the browser. Close it to stop the local server.")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
