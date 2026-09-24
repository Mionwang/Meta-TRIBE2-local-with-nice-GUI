"""Exploratory ROI summaries of TRIBE v2 cortical predictions.

Parcel choices adapt the Apache-2.0 analysis layer in
techfreakworm/tribev2-brain-timeline, commit 56e31aa6. The atlas lookup uses
Meta TRIBE v2's own fsaverage5 HCP-MMP1 helper. These are hypotheses, not
validated attention or retention estimators.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter1d


PARCELS = {
    "orienting_attention": ["TPOJ1", "TPOJ2", "PGi", "PGs", "PFm", "IFJa", "IFJp"],
    "sustained_attention": ["FEF", "LIPv", "LIPd", "VIP", "MIP", "AIP", "IP0", "IP1", "IP2"],
    "cognitive_engagement": ["p9-46v", "a9-46v", "9-46d", "46", "8C", "i6-8", "s6-8"],
    "visual_engagement": ["V1", "V2", "V3", "V4", "V3A", "V3B", "V6", "V6A", "MT", "MST"],
    "auditory_engagement": ["A1", "LBelt", "MBelt", "PBelt", "A4", "A5"],
    "semantic_load": ["44", "45", "IFSa", "STSdp", "STSvp", "STGa", "TE1a", "A5", "PSL", "SFL", "55b"],
    "self_relevance": ["7m", "POS2", "v23ab", "d23ab", "31pv", "31pd", "RSC", "PCV", "9m", "10r", "PGs", "PGi"],
    "virality_proxy": ["10r", "10v", "10d", "10pp", "p32", "s32", "a24", "d32", "25", "OFC", "pOFC", "11l", "13l", "9m"],
}


def masks_for_fsaverage5(cache_dir: Path) -> dict[str, np.ndarray]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "hcp_mmp1_fsaverage5_masks.npz"
    if path.exists():
        with np.load(path, allow_pickle=False) as data:
            masks = {k: data[k] for k in data.files}
        if set(masks) == set(PARCELS) and all(len(v) for v in masks.values()):
            return masks
    # Meta's helper calls mne.datasets.sample.data_path(), which downloads a
    # large unrelated sample dataset from OSF. We use the exact two annotation
    # files and MD5 hashes listed in MNE's fetch_hcp_mmp_parcellation. Vertex
    # selection below follows Meta's get_hcp_labels: take indices <10242 from
    # each hemisphere and offset the right hemisphere by 10242.
    import requests
    from nibabel.freesurfer.io import read_annot
    sample_root = cache_dir.parent / "mne" / "sample"
    label_dir = sample_root / "subjects" / "fsaverage" / "label"
    label_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "lh": ("https://s3-eu-west-1.amazonaws.com/pfigshare-u-files/5528816/lh.HCPMMP1.annot",
               "46a102b59b2fb1bb4bd62d51bf02e975"),
        "rh": ("https://s3-eu-west-1.amazonaws.com/pfigshare-u-files/5528819/rh.HCPMMP1.annot",
               "75e96b331940227bbcb07c1c791c2463"),
    }
    for hemi, (url, expected_md5) in sources.items():
        path = label_dir / f"{hemi}.HCPMMP1.annot"
        if not path.exists() or hashlib.md5(path.read_bytes()).hexdigest() != expected_md5:
            print(f"Downloading verified {hemi} HCP-MMP1 atlas annotation...")
            temp = path.with_suffix(".part")
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                with temp.open("wb") as f:
                    for chunk in response.iter_content(1024 * 1024):
                        f.write(chunk)
            if hashlib.md5(temp.read_bytes()).hexdigest() != expected_md5:
                temp.unlink(missing_ok=True)
                raise RuntimeError(f"Atlas hash mismatch for {hemi} annotation")
            temp.replace(path)
    labels_by_name: dict[str, list[np.ndarray]] = {}
    coverage = 0
    for hemi, offset in (("lh", 0), ("rh", 10242)):
        assignments, _, names = read_annot(label_dir / f"{hemi}.HCPMMP1.annot")
        if len(assignments) != 163842:
            raise RuntimeError(f"Unexpected {hemi} HCP annotation vertex count: {len(assignments)}")
        for label_id, encoded in enumerate(names):
            name = encoded.decode("utf-8")
            if name.startswith(("L_", "R_")):
                name = name[2:]
            name = name.removesuffix("_ROI")
            vertices = np.flatnonzero(assignments[:10242] == label_id).astype(np.int64) + offset
            if len(vertices):
                labels_by_name.setdefault(name, []).append(vertices)
                coverage += len(vertices)
    if coverage != 20484:
        raise RuntimeError(f"HCP annotations cover {coverage} fsaverage5 vertices, expected 20484")
    valid = set(labels_by_name)
    masks = {}
    for name, parcels in PARCELS.items():
        missing = set(parcels) - valid
        if missing:
            print(f"Atlas note: {name}: unavailable parcels: {', '.join(sorted(missing))}")
        present = [p for p in parcels if p in valid]
        if not present:
            raise RuntimeError(f"No valid atlas parcels for {name}; cannot create a truthful score")
        masks[name] = np.unique(np.concatenate([
            vertices for p in present for vertices in labels_by_name[p]
        ]))
    np.savez_compressed(path, **masks)
    return masks


def _z(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    sd = x.std()
    return np.zeros_like(x) if sd < 1e-8 else (x - x.mean()) / sd


def _rank100(x: np.ndarray) -> np.ndarray:
    """Within-video rank; 50 for a constant signal. Never a calibrated score."""
    if np.ptp(x) < 1e-8:
        return np.full(len(x), 50.0)
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x), dtype=float)
    ranks[order] = np.arange(len(x), dtype=float)
    return 100 * ranks / max(len(x) - 1, 1)


def curves_from_predictions(preds: np.ndarray, masks: dict[str, np.ndarray]) -> tuple[dict, dict]:
    preds = np.asarray(preds)
    if preds.ndim != 2 or preds.shape[1] != 20484 or not np.isfinite(preds).all():
        raise ValueError(f"Expected finite TRIBE fsaverage5 predictions (T, 20484), got {preds.shape}")
    if len(preds) < 2:
        raise ValueError("At least two one-second predictions are needed for a timeline")
    raw, z = {}, {}
    for name, idx in masks.items():
        if not len(idx) or np.min(idx) < 0 or np.max(idx) >= preds.shape[1]:
            raise ValueError(f"Invalid {name} ROI mask")
        raw[name] = preds[:, idx].mean(axis=1).astype(float)
        z[name] = gaussian_filter1d(_z(raw[name]), sigma=0.8, mode="nearest")
    z["attention"] = 0.35 * z["orienting_attention"] + 0.40 * z["sustained_attention"] + 0.25 * z["cognitive_engagement"]
    z["engagement_arousal"] = 0.5 * z["visual_engagement"] + 0.5 * z["auditory_engagement"]
    display = {k: _rank100(v) for k, v in z.items()}
    return {"raw": raw, "z": z}, display


def _runs(flag: np.ndarray) -> list[tuple[int, int]]:
    spans = []
    start = None
    for i, yes in enumerate(list(flag) + [False]):
        if yes and start is None:
            start = i
        if not yes and start is not None:
            spans.append((start, i))
            start = None
    return spans


def summarize(times: np.ndarray, z: dict, display: dict) -> dict:
    t = np.asarray(times, dtype=float)
    a = np.asarray(display["attention"])
    az = np.asarray(z["attention"])
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 1.0
    hook = t < min(3.0, t[-1] + dt)
    after_hook = t >= 3.0
    valley_cut = np.percentile(a, 25)
    valleys = []
    for first, stop in _runs(a <= valley_cut):
        valleys.append({"start_s": round(float(t[first]), 2),
                        "end_s": round(float(t[stop - 1] + dt), 2),
                        "mean_within_clip_index": round(float(a[first:stop].mean()), 1)})
    valleys.sort(key=lambda v: v["mean_within_clip_index"])
    peaks = [{"time_s": round(float(t[i]), 2), "within_clip_index": round(float(a[i]), 1)}
             for i in range(len(a)) if a[i] >= np.percentile(a, 90)]
    recoveries = []
    for first, stop in _runs(a <= valley_cut):
        future = np.arange(stop, min(len(a), stop + max(2, int(round(5 / dt)))))
        if not len(future):
            continue
        best = int(future[np.argmax(a[future])])
        gain = float(a[best] - a[first:stop].min())
        if gain >= 20:
            recoveries.append({"time_s": round(float(t[best]), 2), "gain_index_points": round(gain, 1),
                               "from_valley_s": round(float(t[first]), 2)})
    recoveries.sort(key=lambda r: r["gain_index_points"], reverse=True)
    return {
        "scale": "Within-clip 0-100 rank. Relative, experimental neural proxy; not predicted retention or virality.",
        "time_resolution_s": round(dt, 3),
        "hook_strength": round(float(a[hook].mean()), 1),
        "sustained_attention": round(float(a[after_hook].mean()), 1) if after_hook.any() else None,
        "attention_volatility_z_per_step": round(float(np.std(np.diff(az))), 3),
        "weak_sections": valleys[:5],
        "recovery_events": recoveries[:5],
        "major_peaks": peaks[:8],
        "major_valleys": valleys[:5],
        "experimental_virality_proxy_peak_time_s": round(float(t[int(np.argmax(z["virality_proxy"]))]), 2),
        "method": {"model": "facebook/tribev2", "mesh": "fsaverage5", "atlas": "HCP-MMP1",
                   "attention_components": {"orienting": 0.35, "sustained": 0.40, "cognitive": 0.25},
                   "normalization": "ROI means z-scored across this clip; 0.8 s Gaussian smoothing; within-clip rank for display"},
    }


def write_results(output: Path, times: np.ndarray, preds: np.ndarray, provenance: dict, atlas_cache: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    masks = masks_for_fsaverage5(atlas_cache)
    measurements, display = curves_from_predictions(preds, masks)
    times = np.asarray(times, dtype=float)
    if len(times) != len(preds):
        raise ValueError("Prediction rows and segment times differ")
    summary = summarize(times, measurements["z"], display)
    summary["provenance"] = provenance
    source_kind = provenance.get("source_kind", "video")
    if source_kind == "image":
        summary.update(hook_strength=None, sustained_attention=None, weak_sections=[],
                       recovery_events=[], major_peaks=[], major_valleys=[])
        summary["scale"] += " Static image held for six seconds; no temporal edits can be inferred."
    fields = ["time", "attention", "orienting_attention", "sustained_attention", "visual_engagement",
              "auditory_engagement", "cognitive_engagement", "engagement_arousal", "semantic_load",
              "self_relevance", "virality_proxy"]
    with (output / "attention_timeline.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields + [k + "_z" for k in fields[1:]] +
                                [k + "_raw" for k in PARCELS])
        writer.writeheader()
        for i, time in enumerate(times):
            row = {"time": round(float(time), 3)}
            row.update({k: round(float(display[k][i]), 3) for k in fields[1:]})
            row.update({k + "_z": round(float(measurements["z"][k][i]), 6) for k in fields[1:]})
            row.update({k + "_raw": round(float(measurements["raw"][k][i]), 6) for k in PARCELS})
            writer.writerow(row)
    (output / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    fig, ax = plt.subplots(figsize=(11, 4.8), layout="constrained")
    ax.plot(times, display["attention"], color="#155e75", lw=2.4, label="Attention proxy")
    ax.plot(times, display["orienting_attention"], color="#e76f51", alpha=.7, label="Orienting")
    ax.plot(times, display["sustained_attention"], color="#64748b", alpha=.7, label="Sustained")
    for valley in summary["weak_sections"]:
        ax.axvspan(valley["start_s"], valley["end_s"], color="#fca5a5", alpha=.25)
    ax.set(xlabel="Stimulus time (s)", ylabel="Within-input index (0-100)", ylim=(0, 100),
           title="Experimental TRIBE v2 attention proxies")
    ax.grid(alpha=.2)
    ax.legend(loc="lower right", ncol=3, fontsize=8)
    fig.savefig(output / "attention_plot.png", dpi=160)
    plt.close(fig)
    weak = summary["weak_sections"]
    recoveries = summary["recovery_events"]
    advice = []
    if source_kind == "image":
        advice.append("This was a static image held for six seconds. The timeline is not a sequence of visual edits.")
    elif weak:
        w = weak[0]
        cue = "auditory cue" if source_kind in {"audio", "text"} else "visual cue"
        advice.append(f"Review {w['start_s']:.1f}-{w['end_s']:.1f} s for pacing, clarity, or a missing {cue}.")
    if recoveries and source_kind != "image":
        r = recoveries[0]
        advice.append(f"Review the change near {r['time_s']:.1f} s; if it is a reveal, test introducing it slightly earlier.")
    if not advice:
        advice.append("No clear low region was detected at the model's one-second resolution. Review the clip manually.")
    def list_html(items, formatter):
        return "<ul>" + "".join(f"<li>{html.escape(formatter(x))}</li>" for x in items) + "</ul>" if items else "<p>None detected.</p>"
    def fmt(value):
        return "—" if value is None else f"{value}/100"
    metrics_line = (
        "<p>This image was held as a static visual input for six seconds. "
        "The time axis is an analysis setup, not a sequence of changes in the image.</p>"
        if source_kind == "image" else
        f"<p><b>Relative start:</b> {fmt(summary['hook_strength'])} within-input index<br>"
        f"<b>Later response:</b> {fmt(summary['sustained_attention'])} within-input index<br>"
        f"<b>Response volatility:</b> {summary['attention_volatility_z_per_step']} z units per step</p>"
    )
    report = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>TRIBE v2 input report</title>
<style>body{{font:16px/1.5 system-ui;max-width:850px;margin:2rem auto;padding:0 1rem;color:#18324a}}img{{max-width:100%}}.note{{background:#fff4e3;padding:1rem;border-left:4px solid #e69a27}}</style>
<h1>Input response analysis</h1><p class="note"><b>Experimental neural proxies.</b> TRIBE v2 predicts cortical activity, not measured attention, retention, or virality. Scores are relative to this input and must not be interpreted as viewer percentages. Temporal precision is approximately one second.</p>
{metrics_line}
<img src="attention_plot.png" alt="Attention timeline"><h2>Weak sections</h2>{list_html(weak, lambda x: f'{x["start_s"]:.1f}-{x["end_s"]:.1f} s')}
<h2>Strongest recoveries</h2>{list_html(recoveries, lambda x: f'{x["time_s"]:.1f} s, +{x["gain_index_points"]:.1f} within-clip index points')}
<h2>Peaks</h2>{list_html(summary['major_peaks'], lambda x: f'{x["time_s"]:.1f} s')}
<h2>Editing observations</h2>{list_html(advice, str)}
<p>The virality proxy is a cortical value-region curve for experimentation only. It is not calibrated against human attention, retention, or other outcome data.</p>
<p>Raw ROI measurements, normalized curves, and predictions are saved for future calibration.</p></html>"""
    (output / "report.html").write_text(report, encoding="utf-8")
