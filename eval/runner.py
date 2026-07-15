"""Layer-2 eval: simulated-patient conversations against the real agent brain.

The agent here is the *same system prompt and the same live tool endpoints* the
Retell voice agent uses — only the audio layer is swapped for text. A second
LLM plays the patient. Success is judged primarily by FINAL DB STATE
(via /debug/appointments), not by reading the transcript.

Usage:
  BACKEND_URL=http://localhost:8000 python -m eval.runner [--only scenario_id]

Env: GEMINI_API_KEY or OPENAI_API_KEY (see eval/llm.py), BACKEND_URL, EVAL_MODEL.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import os
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "retell"))
from tools import tool_defs  # noqa: E402  (single source of truth with the voice agent)

from eval.llm import completion, make_client  # noqa: E402

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
IST = ZoneInfo("Asia/Kolkata")
MAX_AGENT_STEPS = 8  # tool-loop iterations per agent turn

AGENT_PROMPT = (HERE.parent / "retell" / "prompt.md").read_text()
BEGIN_MESSAGE = ("Thank you for calling Fortis Memorial Research Institute, Gurgaon. "
                 "This is Diya. How may I help you today?")

client, MODEL = make_client()
# generous timeout: free-tier hosts cold-start (~50s) after idle
http = httpx.Client(timeout=90)


def openai_tools() -> list[dict]:
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"],
                      "parameters": t["parameters"]}}
        for t in tool_defs(BACKEND)
    ]


def chat(messages: list[dict], tools: list[dict] | None = None):
    return completion(
        client, model=MODEL, messages=messages, tools=tools or None, temperature=0.4,
    ).choices[0].message


def call_tool(name: str, args: dict) -> tuple[dict, float]:
    for attempt in (1, 2, 3):
        t0 = time.perf_counter()
        try:
            r = http.post(f"{BACKEND}/tools/{name}", json={"args": args})
            ms = (time.perf_counter() - t0) * 1000
            return (r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}), ms
        except httpx.TransportError as e:
            if attempt == 3:
                return {"error": f"backend unreachable: {type(e).__name__}"}, 0.0
            time.sleep(3 * attempt)


def db_state(phone: str) -> dict:
    return http.get(f"{BACKEND}/debug/appointments", params={"phone": phone}).json()


class Sabotage:
    """Mid-conversation failure injection: after the agent's first availability
    search, book the first offered slot out from under it (a rival caller).
    The agent's next book_appointment hits a real conflict and must recover."""

    def __init__(self, enabled: bool):
        self.enabled, self.done = enabled, False

    def maybe_fire(self, tool: str, result: dict) -> None:
        if not self.enabled or self.done or tool != "search_availability":
            return
        slots = result.get("slots") or []
        if slots:
            call_tool("book_appointment", {
                "slot_id": slots[0]["slot_id"], "patient_name": "Rival Caller",
                "patient_phone": "9999999998", "appointment_type": "new_consultation",
            })
            self.done = True


def agent_turn(history: list[dict], tools: list[dict], sabotage: Sabotage,
               tool_log: list[dict]) -> str:
    """Run the receptionist for one turn, executing tool calls against the backend."""
    for _ in range(MAX_AGENT_STEPS):
        msg = chat(history, tools)
        if not msg.tool_calls:
            history.append({"role": "assistant", "content": msg.content or ""})
            return msg.content or ""
        history.append({
            "role": "assistant", "content": msg.content,
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result, ms = call_tool(tc.function.name, args)
            sabotage.maybe_fire(tc.function.name, result)
            tool_log.append({"tool": tc.function.name, "args": args,
                             "result": result, "latency_ms": round(ms, 1)})
            history.append({"role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result)})
    return "I'm sorry, something went wrong on our side. Could you call back in a few minutes?"


def patient_turn(scenario: dict, transcript: list[dict]) -> str:
    convo = "\n".join(f"{t['speaker']}: {t['text']}" for t in transcript)
    system = f"""You are role-playing a PATIENT calling a hospital reception line. Stay fully in character.

Persona: {scenario['patient']['persona']}
Your goal: {scenario['patient']['goal']}

Rules:
- Speak like a real caller on the phone: short, natural, sometimes imprecise.
- Reveal information only when asked (name, phone number, etc.).
- Never break character, never mention being an AI or a test.
- When your goal is achieved (or clearly impossible), say a brief goodbye and append the token [HANGUP].
- Output ONLY your next utterance."""
    msg = chat([{"role": "system", "content": system},
                {"role": "user", "content": f"Conversation so far:\n{convo}\n\nYour next utterance:"}])
    return (msg.content or "").strip()


def run_setup(scenario: dict) -> dict:
    """Pre-create appointments a scenario needs (e.g. something to cancel)."""
    ctx = {}
    for step in scenario.get("setup", []):
        docs, _ = call_tool("find_doctors", {"department": step["department"]})
        doc = docs["doctors"][0]
        avail, _ = call_tool("search_availability", {"doctor_id": doc["doctor_id"]})
        slot = avail["slots"][0]
        booked, _ = call_tool("book_appointment", {
            "slot_id": slot["slot_id"], "patient_name": step["patient_name"],
            "patient_phone": step["phone"], "appointment_type": "new_consultation",
        })
        assert booked.get("booked"), f"setup booking failed: {booked}"
        ctx["setup_appointment"] = booked
    return ctx


def check(assertion: dict, ctx: dict) -> tuple[bool, str]:
    kind = assertion["type"]
    state = db_state(assertion["phone"])
    booked = [a for a in state.get("appointments", []) if a["status"] == "booked"]
    if kind == "booked_count":
        ok = len(booked) == assertion["equals"]
        return ok, f"booked_count={len(booked)} (want {assertion['equals']})"
    if kind == "booked_department_contains":
        want = assertion["value"].lower()
        ok = any(want in a.get("doctor_departments", "").lower() for a in booked)
        return ok, f"departments={[a.get('doctor_departments') for a in booked]} (want ~{assertion['value']})"
    if kind == "cancelled":
        appt_id = ctx["setup_appointment"]["appointment_id"]
        match = [a for a in state.get("appointments", []) if a["appointment_id"] == appt_id]
        ok = bool(match) and match[0]["status"] == "cancelled"
        return ok, f"appointment {appt_id} status={match[0]['status'] if match else 'missing'}"
    if kind == "slot_changed":
        appt_id = ctx["setup_appointment"]["appointment_id"]
        old = ctx["setup_appointment"]["start"]
        match = [a for a in booked if a["appointment_id"] == appt_id]
        ok = bool(match) and match[0]["start"] != old
        return ok, f"start {old} -> {match[0]['start'] if match else 'missing'}"
    return False, f"unknown assertion type {kind}"


def run_scenario(scenario: dict, out_dir: Path) -> dict:
    print(f"\n=== {scenario['id']} ===", file=sys.stderr)
    ctx = run_setup(scenario)
    tools = openai_tools()
    sabotage = Sabotage(scenario.get("sabotage") == "first_offered_slot")
    tool_log: list[dict] = []
    now = datetime.now(IST).strftime("%A, %d %B %Y, %I:%M %p")
    transcript = [{"speaker": "AGENT", "text": BEGIN_MESSAGE}]
    history: list[dict] = [
        {"role": "system", "content": AGENT_PROMPT.replace("{{current_time}}", now)},
        {"role": "assistant", "content": BEGIN_MESSAGE},
    ]

    for _ in range(scenario.get("max_turns", 14)):
        utterance = patient_turn(scenario, transcript)
        hangup = "[HANGUP]" in utterance
        utterance = utterance.replace("[HANGUP]", "").strip()
        if utterance:
            transcript.append({"speaker": "PATIENT", "text": utterance})
            print(f"  PATIENT: {utterance[:100]}", file=sys.stderr)
        if hangup:
            break
        history.append({"role": "user", "content": utterance})
        reply = agent_turn(history, tools, sabotage, tool_log)
        transcript.append({"speaker": "AGENT", "text": reply})
        print(f"  AGENT:   {reply[:100]}", file=sys.stderr)

    checks = []
    for a in scenario.get("assertions", []):
        ok, detail = check(a, ctx)
        checks.append({"type": a["type"], "pass": ok, "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {a['type']}: {detail}", file=sys.stderr)

    latencies = [t["latency_ms"] for t in tool_log]
    result = {
        "id": scenario["id"],
        "description": scenario["description"],
        "passed": all(c["pass"] for c in checks),
        "checks": checks,
        "judge_questions": scenario.get("judge", []),
        "turns": len(transcript),
        "tool_calls": len(tool_log),
        "tool_latency_ms": {
            "p50": round(statistics.median(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "transcript": transcript,
        "tool_log": tool_log,
    }
    (out_dir / f"{scenario['id']}.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run a single scenario id")
    ap.add_argument("--resume", action="store_true",
                    help="skip scenarios that already have a results file (quota-friendly)")
    args = ap.parse_args()

    assert http.get(f"{BACKEND}/health").json().get("ok"), "backend not reachable"
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)

    scenarios = []
    for f in sorted((HERE / "scenarios").glob("*.yaml")):
        scenarios.append(yaml.safe_load(f.read_text()))
    if args.only:
        scenarios = [s for s in scenarios if s["id"] == args.only]

    for s in scenarios:
        if args.resume and (out_dir / f"{s['id']}.json").exists():
            print(f"skip {s['id']} (already done)", file=sys.stderr)
            continue
        run_scenario(s, out_dir)

    results = [json.loads((out_dir / f"{s['id']}.json").read_text())
               for s in scenarios if (out_dir / f"{s['id']}.json").exists()]
    summary = {
        "ran_at": datetime.now(IST).isoformat(),
        "model": MODEL,
        "backend": BACKEND,
        "scenarios": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "results": [{k: r[k] for k in ("id", "passed", "checks", "turns", "tool_calls", "tool_latency_ms")}
                    for r in results],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n{summary['passed']}/{summary['scenarios']} scenarios passed "
          f"→ eval/results/summary.json", file=sys.stderr)


if __name__ == "__main__":
    main()
