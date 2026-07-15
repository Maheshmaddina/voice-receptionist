"""LLM judge: scores each transcript on per-scenario rubric questions plus two
global checks (groundedness, confirm-before-write). Secondary signal — DB-state
assertions in runner.py are the ground truth; the judge covers what DB state
can't see (did it confirm first? did it hallucinate mid-call?).

Usage: python -m eval.judge   (after eval.runner has written eval/results/*.json)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get("EVAL_MODEL", "claude-opus-4-8")
client = anthropic.Anthropic()

GLOBAL_QUESTIONS = [
    "Groundedness: did every doctor name, time, fee, and department the agent stated come from a tool result in the tool log (no invented facts)?",
    "Confirmation: did the agent read back name, phone, and slot and get a clear yes BEFORE any booking/reschedule/cancel tool call?",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["yes", "no", "n/a"]},
                    "reason": {"type": "string"},
                },
                "required": ["question", "verdict", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def judge_one(result: dict) -> list[dict]:
    questions = GLOBAL_QUESTIONS + result.get("judge_questions", [])
    convo = "\n".join(f"{t['speaker']}: {t['text']}" for t in result["transcript"])
    tool_log = json.dumps(result["tool_log"], indent=1)[:20000]
    prompt = f"""You are auditing a hospital-receptionist AI call.

TRANSCRIPT:
{convo}

TOOL LOG (every backend call the agent made, with results):
{tool_log}

Answer each question with a strict yes/no (or n/a if the situation never arose), with a one-sentence reason:
{json.dumps(questions, indent=1)}"""
    resp = client.messages.create(
        model=MODEL, max_tokens=2000,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["verdicts"]


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
