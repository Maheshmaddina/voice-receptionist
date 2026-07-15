"""Layer-3 eval: pull real call transcripts + latency metrics from Retell.

Make a few live calls to the deployed agent (phone or dashboard web call),
then run this to aggregate what actually happened on the wire:
end-to-end / LLM / TTS latency percentiles, disconnect reasons, call success.

Usage: RETELL_API_KEY=... python -m eval.live.latency [--limit 20]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

from retell import Retell

HERE = Path(__file__).resolve().parent
STATE = HERE.parent.parent / "retell" / "state.json"


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, round(p / 100 * (len(values) - 1)))
    return round(values[idx], 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    client = Retell(api_key=os.environ["RETELL_API_KEY"])
    agent_id = json.loads(STATE.read_text())["agent_id"] if STATE.exists() else None

    calls = client.call.list(filter_criteria={"agent_id": [agent_id]} if agent_id else None,
                             limit=args.limit)
    rows, e2e_p50s, e2e_p90s, llm_p50s, tts_p50s = [], [], [], [], []
    for c in calls:
        lat = getattr(c, "latency", None)
        row = {
            "call_id": c.call_id,
            "status": getattr(c, "call_status", None),
            "disconnection_reason": getattr(c, "disconnection_reason", None),
            "duration_ms": getattr(c, "duration_ms", None),
        }
        if lat:
            for comp, bucket in (("e2e", e2e_p50s), ("llm", llm_p50s), ("tts", tts_p50s)):
                comp_lat = getattr(lat, comp, None)
                if comp_lat and getattr(comp_lat, "p50", None) is not None:
                    row[f"{comp}_p50_ms"] = comp_lat.p50
                    bucket.append(comp_lat.p50)
            e2e = getattr(lat, "e2e", None)
            if e2e and getattr(e2e, "p90", None) is not None:
                row["e2e_p90_ms"] = e2e.p90
                e2e_p90s.append(e2e.p90)
        rows.append(row)

    report = {
        "calls_analyzed": len(rows),
        "aggregate": {
            "e2e_p50_ms": pct(e2e_p50s, 50),
            "e2e_p90_ms": pct(e2e_p90s, 50),  # median of per-call p90s
            "llm_p50_ms": pct(llm_p50s, 50),
            "tts_p50_ms": pct(tts_p50s, 50),
        },
        "calls": rows,
    }
    out = HERE / "latency_report.json"
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["aggregate"], indent=2))
    print(f"full report → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
