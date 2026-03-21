# app/engine/auto_threshold.py

from typing import Dict, Any
import numpy as np

METRICS = ["sbp", "dbp", "pp", "hr"]


def compute_noise_band(steady_result: Dict[str, Any]) -> Dict[str, float]:
    """
    基于 baseline IQR 自动生成个体噪声带：
    noise_band = IQR × 2
    """
    windows = steady_result.get("windows", {})
    if "30d" not in windows:
        return {m: 10 for m in METRICS}

    baseline = windows["30d"]["baseline"]["profile"]
    return {m: baseline[m]["iqr"] * 2 for m in METRICS}


def compute_velocity_threshold(records) -> Dict[str, float]:
    """
    基于 Δ分布自动生成急剧变化阈值：
    threshold = mean(|Δ|) + 2 × std(|Δ|)
    """
    deltas = {m: [] for m in METRICS}

    for i in range(1, len(records)):
        for m in METRICS:
            deltas[m].append(abs(records[i][m] - records[i - 1][m]))

    thresholds = {}
    for m in METRICS:
        arr = np.array(deltas[m])
        if len(arr) < 5:
            thresholds[m] = 15
        else:
            thresholds[m] = float(arr.mean() + 2 * arr.std())

    return thresholds


def compute_sync_threshold(steady_result: Dict[str, Any]) -> Dict[str, float]:
    """
    基于 30d delta 自动生成同步偏移阈值：
    threshold = |delta_30d| × 1.5
    """
    traj = steady_result.get("trajectory", {})
    thresholds = {}

    for m in METRICS:
        steps = traj.get(m, [])
        if not steps:
            thresholds[m] = 10
            continue
        delta = abs(steps[-1]["delta"])
        thresholds[m] = max(6, delta * 1.5)

    return thresholds


def auto_thresholds(records, steady_result):
    return {
        "noise_band": compute_noise_band(steady_result),
        "velocity": compute_velocity_threshold(records),
        "sync": compute_sync_threshold(steady_result),
    }
