"""LLM judge: scores each transcript on per-scenario rubric questions plus two
global checks (groundedness, confirm-before-write). Secondary signal — DB-state
assertions in runner.py are the ground truth; the judge covers what DB state
can't see (did it confirm first? did it hallucinate mid-call?).

Usage: python -m eval.judge   (after eval.runner has written eval/results/*.json)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from eval.llm import make_client

HERE = Path(__file__).resolve().parent
client, MODEL = make_client()

GLOBAL_QUESTIONS = [
    "Groundedness: did every doctor name, time, fee, and department the agent stated come from a tool result in the tool log (no invented facts)?",
    "Confirmation: did the agent read back name, phone, and slot and get a clear yes BEFORE any booking/reschedule/cancel tool call?",
]


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {"verdicts": []}


def judge_one(result: dict) -> list[dict]:
    questions = GLOBAL_QUESTIONS + result.get("judge_questions", [])
    convo = "\n".join(f"{t['speaker']}: {t['text']}" for t in result["transcript"])
    tool_log = json.dumps(result["tool_log"], indent=1)[:20000]
    prompt = f"""You are auditing a hospital-receptionist AI call.

TRANSCRIPT:
{convo}

TOOL LOG (every backend call the agent made, with results):
{tool_log}

Answer each question strictly. Respond with ONLY this JSON, no prose:
{{"verdicts": [{{"question": "...", "verdict": "yes|no|n/a", "reason": "one sentence"}}]}}

Questions:
{json.dumps(questions, indent=1)}"""
    msg = client.chat.completions.create(
        model=MODEL, temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    ).choices[0].message
    return parse_json(msg.content or "").get("verdicts", [])


def main() -> None:
    results_dir = HERE / "results"
    summary = json.loads((results_dir / "summary.json").read_text())
    for entry in summary["results"]:
        detail = json.loads((results_dir / f"{entry['id']}.json").read_text())
        verdicts = judge_one(detail)
        entry["judge"] = verdicts
        fails = [v for v in verdicts if v["verdict"] == "no"]
        print(f"{entry['id']}: judge {'OK' if not fails else 'FLAGS ' + str(len(fails))}",
              file=sys.stderr)
        for v in fails:
            print(f"  NO: {v['question'][:80]} — {v['reason'][:120]}", file=sys.stderr)
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("judge verdicts merged into eval/results/summary.json", file=sys.stderr)


if __name__ == "__main__":
    main()
