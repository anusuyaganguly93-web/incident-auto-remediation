"""
Filters raw log lines down to WARN/ERROR only, and clusters them by a
crude normalized message (strips numbers) so repeated identical errors
collapse into one entry with a count — this is what keeps the evidence
payload handed to the LLM small (fewer tokens = faster call = stays
inside the per-call latency budget).
"""
import re
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class LogCluster:
    normalized_msg: str
    level: str
    count: int
    example_ts: str


LEVEL_RANK = {"INFO": 0, "WARN": 1, "ERROR": 2}


def filter_logs_by_error_level(
    log_lines: list[dict], min_level: str = "WARN"
) -> list[LogCluster]:
    min_rank = LEVEL_RANK[min_level]
    filtered = [l for l in log_lines if LEVEL_RANK.get(l["level"], 0) >= min_rank]

    clusters: dict[tuple[str, str], list[dict]] = {}
    for line in filtered:
        normalized = _normalize(line["msg"])
        key = (line["level"], normalized)
        clusters.setdefault(key, []).append(line)

    results = []
    for (level, normalized), lines in clusters.items():
        results.append(
            LogCluster(
                normalized_msg=normalized,
                level=level,
                count=len(lines),
                example_ts=lines[0]["ts"],
            )
        )

    # highest severity + highest count first — most important evidence up top
    results.sort(key=lambda c: (LEVEL_RANK[c.level], c.count), reverse=True)
    return results


def _normalize(msg: str) -> str:
    """Strips numbers so 'timed out after 5000ms' x N collapses to one cluster."""
    return re.sub(r"\d+", "N", msg)
