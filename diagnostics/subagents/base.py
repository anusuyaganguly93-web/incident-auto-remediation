"""
Common return shape for every diagnostic subagent, so run_diagnostics.py
can merge them uniformly regardless of which subagent produced what.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    subagent: str          # "metrics" | "logs" | "deploy_history" | "runbook"
    finding: str            # short human-readable finding, fed into the LLM prompt
    raw: dict[str, Any] = field(default_factory=dict)   # full detail, stored in Postgres, NOT sent to LLM
    latency_ms: float = 0.0
