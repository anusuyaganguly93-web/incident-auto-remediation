"""
Simple statistical anomaly detector. Deliberately NOT an LLM call —
this is the "scripts do detection, LLM does interpretation" principle
from the design: keeps latency low and keeps the LLM's job to
summarizing/reasoning about evidence a script already found, not
scanning raw numbers itself.

Splits a series into a baseline window and a recent window, and flags
an anomaly if the recent mean deviates from the baseline mean by more
than `z_threshold` standard deviations of the baseline.
"""
import statistics
from dataclasses import dataclass


@dataclass
class AnomalyResult:
    metric_name: str
    is_anomalous: bool
    baseline_mean: float
    recent_mean: float
    z_score: float
    pct_change: float


def detect_anomaly(
    series: list[float],
    metric_name: str,
    baseline_window: int = 10,
    recent_window: int = 6,
    z_threshold: float = 3.0,
) -> AnomalyResult:
    if len(series) < baseline_window + 1:
        raise ValueError(f"series too short for baseline_window={baseline_window}")

    baseline = series[:baseline_window]
    recent = series[-recent_window:]

    baseline_mean = statistics.mean(baseline)
    baseline_stdev = statistics.pstdev(baseline) or 0.01  # avoid div-by-zero on flat series
    recent_mean = statistics.mean(recent)

    z_score = (recent_mean - baseline_mean) / baseline_stdev
    pct_change = ((recent_mean - baseline_mean) / baseline_mean) * 100 if baseline_mean else 0.0

    return AnomalyResult(
        metric_name=metric_name,
        is_anomalous=abs(z_score) >= z_threshold,
        baseline_mean=round(baseline_mean, 2),
        recent_mean=round(recent_mean, 2),
        z_score=round(z_score, 2),
        pct_change=round(pct_change, 1),
    )
