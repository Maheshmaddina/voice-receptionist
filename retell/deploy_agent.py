"""Create or update the Retell voice agent (LLM + agent, optionally a phone number).

Usage:
  RETELL_API_KEY=... BACKEND_URL=https://<deployed-backend> python retell/deploy_agent.py
  python retell/deploy_agent.py --dry-run     # just write retell/agent_config.json

State (llm_id / agent_id / phone number) persists in retell/state.json so re-runs
update the same agent instead of creating duplicates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tools import tool_defs  # noqa: E402

STATE_FILE = HERE / "state.json"
PROMPT = (HERE / "prompt.md").read_text()

MODEL = os.environ.get("RETELL_MODEL", "gpt-4.1")
VOICE_ID = os.environ.get("RETELL_VOICE_ID", "11labs-Anaya")  # Indian English female


def build_config(backend_url: str) -> dict:
    return {
        "llm": {
            "model": MODEL,
            "model_temperature": 0,
            "model_high_priority": True,  # dedicated capacity → lower, steadier LLM latency
            "general_prompt": PROMPT,
            "begin_message": "Thank you for calling Fortis Memorial Research Institute, Gurgaon. This is Diya. How may I help you today?",
            "general_tools": tool_defs(backend_url),
        },
        "agent": {
            "agent_name": "FMRI Gurgaon Receptionist",
            "language": "en-IN",
            "voice_id": VOICE_ID,
            "responsiveness": 0.8,
            "interruption_sensitivity": 0.8,
            "enable_backchannel": True,
            "normalize_for_speech": True,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="write agent_config.json and exit")
    ap.add_argument("--buy-number", action="store_true", help="also provision a phone number")
    args = ap.parse_args()

    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")
    config = build_config(backend_url)
    (HERE / "agent_config.json").write_text(json.dumps(config, indent=2))
    print(f"wrote agent_config.json (backend: {backend_url})")
    if args.dry_run:
        return

    from retell import Retell

    client = Retell(api_key=os.environ["RETELL_API_KEY"])
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

    if state.get("llm_id"):
        llm = client.llm.update(state["llm_id"], **config["llm"])
        print("updated LLM", llm.llm_id)
    else:
        llm = client.llm.create(**config["llm"])
        print("created LLM", llm.llm_id)
    state["llm_id"] = llm.llm_id

    agent_kwargs = {
        **config["agent"],
        "response_engine": {"type": "retell-llm", "llm_id": llm.llm_id},
    }
    if state.get("agent_id"):
        agent = client.agent.update(state["agent_id"], **agent_kwargs)
        print("updated agent", agent.agent_id)
    else:
        agent = client.agent.create(**agent_kwargs)
        print("created agent", agent.agent_id)
    state["agent_id"] = agent.agent_id

    if args.buy_number and not state.get("phone_number"):
        number = client.phone_number.create(inbound_agent_id=agent.agent_id)
        state["phone_number"] = number.phone_number
        print("provisioned number:", number.phone_number)
    elif state.get("phone_number"):
        client.phone_number.update(state["phone_number"], inbound_agent_id=agent.agent_id)
        print("number bound:", state["phone_number"])

    STATE_FILE.write_text(json.dumps(state, indent=2))
    print("state saved → retell/state.json")


if __name__ == "__main__":
    main()
