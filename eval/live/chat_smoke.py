"""End-to-end smoke of the DEPLOYED agent brain via Retell's Chat API.

This exercises the exact production path minus audio: Retell runs GPT-4.1 with
our prompt + tools server-side, tool calls hit the deployed backend over the
public internet, and we verify the booking landed in the production DB.

A scripted patient keeps it dependency-free (no eval LLM key needed).

Usage: RETELL_API_KEY=... [BACKEND_URL=...] python -m eval.live.chat_smoke
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from retell import Retell

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE.parent.parent / "retell" / "state.json"
BACKEND = os.environ.get("BACKEND_URL", "https://fmri-receptionist-backend.onrender.com").rstrip("/")
PHONE = "9899000111"

SCRIPT = [
    "Hi, I have a skin rash, I'd like to see a dermatologist this week please.",
    "Any of those days work. Give me the first one.",
    "My name is Smoke Test Patient, and my mobile number is nine eight nine nine, zero zero zero, one one one.",
    "It's a new consultation. Yes, please go ahead and book it.",
    "Yes, that's correct. Please confirm.",
    "No that's all, thank you!",
]


def main() -> None:
    client = Retell(api_key=os.environ["RETELL_API_KEY"])
    state = json.loads(STATE_FILE.read_text())

    if not state.get("chat_agent_id"):
        ca = client.chat_agent.create(
            agent_name="FMRI Receptionist (chat smoke)",
            response_engine={"type": "retell-llm", "llm_id": state["llm_id"]},
            language="en-IN",
        )
        state["chat_agent_id"] = ca.agent_id
        STATE_FILE.write_text(json.dumps(state, indent=2))
        print("created chat agent", ca.agent_id, file=sys.stderr)

    chat = client.chat.create(agent_id=state["chat_agent_id"])
    print("chat id:", chat.chat_id, file=sys.stderr)

    for line in SCRIPT:
        print(f"\nPATIENT: {line}", file=sys.stderr)
        t0 = time.perf_counter()
        resp = client.chat.create_chat_completion(chat_id=chat.chat_id, content=line)
        dt = time.perf_counter() - t0
        for m in resp.messages or []:
            content = getattr(m, "content", None)
            if content:
                print(f"AGENT ({dt:.1f}s): {content}", file=sys.stderr)

    # ground truth: did the booking land in the production DB?
    r = httpx.get(f"{BACKEND}/debug/appointments", params={"phone": PHONE}, timeout=30).json()
    booked = [a for a in r.get("appointments", []) if a["status"] == "booked"]
    print("\nDB check — booked appointments for smoke patient:", len(booked), file=sys.stderr)
    for a in booked:
        print("  ", a["doctor"], "|", a["spoken"], "|", a.get("doctor_departments"), file=sys.stderr)
    if not booked:
        sys.exit("SMOKE FAIL: no booking found in production DB")
    print("SMOKE PASS", file=sys.stderr)


if __name__ == "__main__":
    main()
