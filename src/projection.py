"""Toy "projected performance" scores built from TRIBE's raw ROI activity.

This is an experiment, not a forecast. Nothing here was fitted to real
Instagram data. It turns a few cross-clip-comparable brain-response features
into 0-100 factor scores; the browser multiplies them against a baseline view
count the user chooses to get playful view/like/comment numbers.

Only the *_raw ROI columns are used: the 0-100 display indices and z-scores are
normalised within each clip and cannot be compared between clips.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

# Typical spread of raw ROI means seen in TRIBE v2 fsaverage5 predictions.
RAW_SCALE = 0.08
SPREAD_SCALE = 0.05
WEIGHTS = {"hook": 0.30, "hold": 0.20, "value": 0.20, "arousal": 0.15, "dynamics": 0.15}
LABELS = {
    "hook": "Opening pull (first 3 s attention-network activity)",
    "hold": "Hold (attention-network activity after 3 s)",
    "value": "Value response (the virality-proxy regions)",
    "arousal": "Sensory intensity (visual + auditory cortex)",
    "dynamics": "Variation (how much the response moves)",
    "talk": "Talkability (language + self-relevance regions)",
}

_CACHE: dict[str, tuple[float, dict | None]] = {}


def _squash(x: float, scale: float = RAW_SCALE) -> float:
    return 50.0 + 50.0 * math.tanh(x / scale)


def raw_features(csv_path: Path) -> dict | None:
    """Cross-clip features from one attention_timeline.csv (cached by mtime)."""
    try:
        mtime = csv_path.stat().st_mtime
    except OSError:
        return None
    key = str(csv_path)
    if key in _CACHE and _CACHE[key][0] == mtime:
        return _CACHE[key][1]
    value = None
    try:
        with csv_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        need = ["time", "orienting_attention_raw", "sustained_attention_raw", "cognitive_engagement_raw",
                "visual_engagement_raw", "auditory_engagement_raw", "semantic_load_raw",
                "self_relevance_raw", "virality_proxy_raw"]
        if len(rows) >= 2 and all(k in rows[0] for k in need):
            col = {k: [float(r[k]) for r in rows] for k in need}
            att = [.35 * a + .40 * b + .25 * c for a, b, c in zip(
                col["orienting_attention_raw"], col["sustained_attention_raw"], col["cognitive_engagement_raw"])]
            t = col["time"]
            head = [a for a, ti in zip(att, t) if ti < 3.0] or att[:1]
            tail = [a for a, ti in zip(att, t) if ti >= 3.0] or att
            mean = lambda xs: sum(xs) / len(xs)
            sd = math.sqrt(mean([(a - mean(att)) ** 2 for a in att]))
            step = (t[-1] - t[0]) / max(len(t) - 1, 1)
            value = {
                "hook": mean(head),
                "hold": mean(tail),
                "value": 0.6 * mean(col["virality_proxy_raw"]) + 0.4 * max(col["virality_proxy_raw"]),
                "arousal": 0.5 * mean(col["visual_engagement_raw"]) + 0.5 * mean(col["auditory_engagement_raw"]),
                "dynamics": sd,
                "talk": 0.5 * mean(col["semantic_load_raw"]) + 0.5 * mean(col["self_relevance_raw"]),
                "duration_s": round(t[-1] - t[0] + (step or 1.0), 2),
            }
    except (OSError, ValueError, KeyError):
        value = None
    _CACHE[key] = (mtime, value)
    return value


def _absolute_score(name: str, x: float) -> float:
    if name == "dynamics":
        return 100.0 * math.tanh(x / SPREAD_SCALE)
    return _squash(x)


def score(features: dict, others: list[dict]) -> dict:
    """0-100 factor scores; blends an absolute scale with rank among your other analyses."""
    blend = min(0.6, len(others) / 15)  # the more you analyze, the more it ranks against your own work
    factors = {}
    for name in [*WEIGHTS, "talk"]:
        absolute = _absolute_score(name, features[name])
        if others:
            below = sum(1 for f in others if f[name] < features[name])
            ties = sum(1 for f in others if f[name] == features[name])
            relative = 100.0 * (below + 0.5 * ties) / len(others)
        else:
            relative = absolute
        factors[name] = round((1 - blend) * absolute + blend * relative, 1)
    composite = sum(WEIGHTS[k] * factors[k] for k in WEIGHTS)
    return {
        "score": round(composite, 1),
        "factors": factors,
        "weights": WEIGHTS,
        "labels": LABELS,
        "duration_s": features["duration_s"],
        "library_size": len(others) + 1,
        "library_weight": round(blend, 2),
    }
