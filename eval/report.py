"""Aggregate eval results into eval/RESULTS.md.

Usage: python -m eval.report
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    summary = json.loads((HERE / "results" / "summary.json").read_text())
    lines = [
        "# Eval Results",
        "",
        f"- **Ran:** {summary['ran_at']}  |  **Model (sim/judge):** {summary['model']}  |  **Backend:** {summary['backend']}",
        f"- **Task success (DB-verified): {summary['passed']}/{summary['scenarios']}**",
        "",
        "| Scenario | DB-verified | Turns | Tool calls | Tool p50 (ms) | Judge flags |",
        "|---|---|---|---|---|---|",
    ]
    all_latencies = []
    for r in summary["results"]:
        judge = r.get("judge", [])
        flags = [v for v in judge if v["verdict"] == "no"]
        p50 = r["tool_latency_ms"]["p50"]
        if p50:
            all_latencies.append(p50)
        lines.append(
            f"| {r['id']} | {'✅ PASS' if r['passed'] else '❌ FAIL'} | {r['turns']} "
            f"| {r['tool_calls']} | {p50} | {len(flags) if judge else '—'} |"
        )

    lines += ["", "## Failed checks / judge flags", ""]
    clean = True
    for r in summary["results"]:
        for c in r["checks"]:
            if not c["pass"]:
                clean = False
                lines.append(f"- **{r['id']}** [db] {c['type']}: {c['detail']}")
        for v in r.get("judge", []):
            if v["verdict"] == "no":
                clean = False
                lines.append(f"- **{r['id']}** [judge] {v['question'][:90]} — {v['reason']}")
    if clean:
        lines.append("_None._")

    lines += [
        "",
        "## Reading these numbers",
        "",
        "- **DB-verified** is the primary signal: after the conversation, the database either",
        "  contains exactly the right appointment (right patient, right department, right status) or it doesn't.",
        "- **Judge flags** cover what DB state can't see: groundedness (no invented doctors/slots)",
        "  and confirm-before-write behavior. LLM-judged, so treat as directional.",
        "- **Tool p50** is backend HTTP latency as seen by the agent — the component of voice",
        "  latency this repo owns. Full per-call latency (STT/LLM/TTS) comes from `eval/live/`.",
    ]
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("wrote eval/RESULTS.md")


if __name__ == "__main__":
    main()
