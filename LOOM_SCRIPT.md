# Loom Script (max 3:00)

> Before recording: backend deployed + seeded, agent live on the phone number,
> `eval/RESULTS.md` open in a tab, Retell dashboard call history open.

## 0:00–0:20 — Setup shot
- Screen: README architecture diagram.
- Say: "This is a voice receptionist for Fortis Memorial Research Institute,
  Gurgaon — a real hospital. 154 real doctors and 34 departments scraped from
  their official directory. Retell handles voice; every fact the agent speaks
  comes from a FastAPI + Postgres backend over tool calls."

## 0:20–1:50 — Live call (the core)
- Call the number on speaker, screen on the Retell live-call view or DB.
- Script the call to hit **booking + one failure**:
  1. "Hi, I need to see a heart doctor next week, mornings if possible."
  2. Let it offer options → pick one.
  3. Give name + phone; **change your mind once** ("actually, evening works
     better") to show re-search.
  4. Confirm. Wait for read-back.
- Immediately show the appointment row: `curl <backend>/debug/appointments?phone=...`
  — "the booking is real, in Postgres, not a transcript artifact."

## 1:50–2:50 — Design decisions (60s)
- Screen: split — `retell/prompt.md` and `eval/RESULTS.md`.
- Say, roughly:
  - "Prompt is ~400 tokens. Reasoning lives in tool results — conflicts return
    alternatives, ambiguity returns choices — so the agent always has a next
    step and the prompt stays fast and drift-free."
  - "Double-booking is impossible by construction: atomic slot claim, plus
    idempotency keys so Retell's webhook retries can't duplicate."
  - "The eval scores final database state, not transcripts — 9 scenarios
    weighted toward failure: a rival steals your slot mid-call, impossible
    times, changed minds. Here are the pass rates and measured latency."
  - Point at e2e p50/p90 from `eval/live/latency_report.json`.

## 2:50–3:00 — Close
- "Repo runs with make setup / make serve / make eval; the number stays live
  for you to test. Thanks."
