# Voice AI Receptionist — Build Plan

## Context

Assignment: build a **voice AI agent that acts as a hospital receptionist** — patients call in, speak naturally, and get an appointment **booked / rescheduled / cancelled**, with conflict resolution and graceful recovery, no human involved. It must run **end-to-end on real clinic data**, be **deployed and independently callable**, and ship with a **re-runnable eval harness**.

Decisions already made:
- **Stack: Retell** (justified below).
- **Clinic: a real Indian hospital** — targeting **Fortis Memorial Research Institute (FMRI), Gurgaon** (single, concrete clinic → clean "the agent knows *this* clinic" story).
- This document is the design for review before any code is written.

Grading rubric (all "Core"): works E2E on real data · handles mid-conversation failure · latency thinking reflected in stack · meaningful eval harness · clean prompt without bloat · actually runnable.

---

## 1. Stack decision — why Retell

Retell offers two integration models; we use the **Retell-LLM + Custom Functions** model, not the self-hosted Custom-LLM WebSocket model.

- **Latency is the product.** Retell owns STT, TTS, VAD/endpointing, turn-taking and interruption handling — the hardest latency/naturalness problems — and they're tuned out of the box. Self-hosting the LLM loop (WebSocket) adds a network hop and forfeits that tuning. Our latency lever becomes **tool-call speed + LLM/prompt size**, which we control.
- **Deployability & "independently callable."** Retell gives a hosted phone number + webhook backend model. Graders call a real number; the LLM runs in Retell; our real logic lives behind function webhooks. Minimal glue.
- **Clean tool-calling.** Custom Functions map 1:1 to our backend endpoints (POST with JSON args, `X-Retell-Signature` for verification, 200-299 = success, result capped 15k chars).
- Bolna was the alternative (more open/self-hostable, good for cost or India telephony) but is more assembly — wrong trade for a 2–3 day budget. This reasoning goes in the README.

---

## 2. Real clinic data

**Target:** Fortis Memorial Research Institute, Gurgaon (real doctors, real departments/specialities).

**Constraint found during research:** `fortishealthcare.com` doctor pages return **HTTP 403 to automated fetchers** (bot protection). Plan handles this:

1. **Scraper** (`scraper/`) uses **Playwright (headless Chromium, real UA + browser context)** to render the FMRI doctor directory and `/specialities`, extracting: doctor name, department/specialty, designation, and OPD/consultation info where present.
2. **Fallback source** if Playwright is still blocked: a structured-JSON source (Apollo247 doctor-listing JSON endpoints) or a scrapeable aggregator (Credihealth/Vaidam) for the same Fortis hospital — documented, with the exact source URL and scrape date.
3. Scraper output is committed as a **frozen snapshot** `data/fortis_fmri_raw.json` (+ `data/PROVENANCE.md` with source URL + date). **Why frozen:** makes the repo runnable offline and the eval deterministic, while the data remains genuinely real/sourced. Re-scrape is a documented `make scrape` command.

**Data model derived from the real data:**
- **Doctors** — real names, specialty, designation, department.
- **Departments/specialities** — real list from `/specialities`.
- **Appointment types** — New Consultation, Follow-up, Teleconsultation (real Fortis categories), with realistic durations (e.g. 30/15/20 min).
- **Slots** — generated as a bookable grid **from each doctor's real OPD day/time pattern** where available, else a realistic default OPD template. This is legitimate: doctors/departments are real; slot *availability* is synthesized on top of real schedules (documented as such).

---

## 3. Architecture

```
Patient phone call
      │
      ▼
┌──────────────┐   Custom Function webhooks (POST, signed)   ┌────────────────────┐
│   Retell     │ ─────────────────────────────────────────► │  FastAPI backend   │
│  (STT/LLM/   │ ◄───────────────── JSON result ──────────── │  (tool endpoints)  │
│   TTS +      │                                             │        │           │
│  prompt +    │                                             │        ▼           │
│  tool defs)  │                                             │   Postgres (real   │
└──────────────┘                                             │   doctors/slots/   │
                                                             │   appointments)    │
                                                             └────────────────────┘
```

- **Retell**: single-prompt Retell-LLM agent; system prompt + tool schemas defined via Retell API (committed as `retell/agent_config.json`, pushed by `scripts/deploy_agent.py`). Fast underlying model (GPT-4o-mini or Claude Haiku tier) for low LLM latency.
- **Backend**: **FastAPI + SQLAlchemy + Postgres** (SQLite fallback for zero-setup local dev). Stateless; all state in DB. Signature verification middleware for Retell webhooks.
- **DB**: real doctors, departments, appointment_types, slots, appointments, patients.

---

## 4. Backend — tools & logic

Each tool = one FastAPI endpoint, returning compact JSON the LLM can speak.

| Tool | Purpose | Key logic |
|------|---------|-----------|
| `get_clinic_info` | hours, departments, address | static from DB |
| `find_doctors` | by department / specialty / name | fuzzy match on real names |
| `search_availability` | open slots for doctor/dept over a date range | filters `slots` not linked to active appt |
| `book_appointment` | create appt | **atomic slot claim** (row-lock / unique constraint) → no double-booking; idempotency key |
| `reschedule_appointment` | move existing appt | free old slot + claim new atomically |
| `cancel_appointment` | cancel | releases slot |
| `lookup_appointments` | find patient's appts by phone | for reschedule/cancel/"what do I have" |

**Robustness logic (directly targets the "things going wrong" rubric):**
- **Conflict handling**: unique constraint on `(doctor_id, slot_start)` for active appts → concurrent/double booking impossible; on clash the tool returns `alternatives` (nearest open slots) so the agent can offer options instead of failing.
- **Idempotency**: `book`/`reschedule`/`cancel` take a client idempotency key; retries (Retell retries failed calls up to 2×) don't create duplicates.
- **Vague/partial input**: tools accept partial params and return disambiguation data (e.g. multiple doctors matched → list) rather than erroring.
- **Validation**: past dates, closed departments, unknown doctor → structured error messages the agent turns into natural recovery.

---

## 5. Agent prompt design (clean, no bloat)

- **Single tight system prompt** (`retell/prompt.md`): role, clinic identity, the 3 lifecycle flows, guardrails (only book real doctors/slots — never invent; always confirm name+phone+slot before writing; read back confirmations), tone (warm, concise, spoken-not-written), and an explicit **error-recovery policy** (on tool error/no availability → apologize briefly, offer nearest alternatives, never dead-end).
- **Reasoning lives in tool results, not the prompt.** Availability, disambiguation lists, and alternatives come from the backend, so the prompt stays small (target < ~600 tokens) → lower latency, less drift. This is deliberate and called out in the README.
- **Mid-conversation change of mind**: prompt instructs the agent to treat the latest stated intent as truth and re-query tools rather than trusting earlier turns; slot claims only happen at explicit confirmation.

---

## 6. Eval harness (the differentiator) — `eval/`

Three layers; **core layers need only the backend URL + an LLM key**, so graders can re-run without telephony.

**Layer 1 — Backend integration tests (`pytest`, deterministic).**
Double-booking prevention, idempotency, reschedule frees old slot, cancel releases slot, conflict → alternatives, invalid input handling. Fast, fully reproducible.

**Layer 2 — Agent conversation eval (text, re-runnable).**
A **simulated-patient LLM** (Anthropic API) drives multi-turn conversations against an agent runner that uses the **exact same system prompt + the exact same live tool endpoints**. Scenarios in `eval/scenarios/*.yaml`, including the hard cases: mid-conversation change of mind, vague request ("sometime next week with a heart doctor"), no-availability/conflict, wrong-then-corrected info, cancel-then-rebook. Scored by:
- **Programmatic assertions** against **final DB state** (did the right appointment actually get created/moved/deleted?) — the ground-truth signal, not vibes.
- **LLM judge** (rubric) for groundedness (no invented doctors/slots), recovery quality, and whether it confirmed before writing.

**Layer 3 — Live voice smoke + latency (`eval/live/`, optional, needs Retell key).**
Use Retell REST API to launch web/phone calls for a few scenarios, pull transcript + **latency metrics (e2e p50/p90, LLM latency, TTS latency)**. This is the source of the README's real latency numbers.

**Metrics reported** (`eval/report.py` → `eval/RESULTS.md`):
- Task success rate (DB-verified) · tool-call accuracy · turns-to-completion · groundedness/hallucination rate · error-recovery success rate · latency p50/p90.

**Why these dimensions** (documented in `eval/README.md`): they map 1:1 to the rubric — success = "works E2E", recovery/groundedness = "things going wrong" + "real data", latency = "stack reflects latency thinking". **Stated shortcomings**: text-layer eval doesn't capture STT errors, barge-in, or accent/audio robustness (only Layer 3 touches those, and with few samples); LLM-judge has variance (mitigated by DB-state ground truth as the primary signal).

---

## 7. Repo structure

```
voice-receptionist/
├── README.md                 # what/why, latency story, limitations
├── Makefile                  # setup, scrape, seed, serve, deploy-agent, eval
├── docker-compose.yml        # postgres + backend (one-command run)
├── .env.example
├── data/
│   ├── fortis_fmri_raw.json  # frozen real-data snapshot
│   └── PROVENANCE.md         # source URL + scrape date + method
├── scraper/                  # Playwright scraper → data snapshot
├── backend/
│   ├── app/ (main.py, models.py, tools/*.py, conflict.py, security.py)
│   ├── seed.py               # snapshot → DB + slot generation
│   └── tests/                # Layer 1 pytest
├── retell/
│   ├── prompt.md
│   ├── agent_config.json
│   └── deploy_agent.py       # push prompt+tools to Retell
└── eval/
    ├── scenarios/*.yaml
    ├── runner.py             # simulated patient + agent + live tools
    ├── judge.py
    ├── live/                 # Layer 3
    ├── report.py
    ├── RESULTS.md            # committed run output
    └── README.md             # dimensions + shortcomings
```

---

## 8. Latency story (for README)

- Retell owns STT/TTS/turn-taking (already optimized) → we don't fight that.
- Our levers: **(a)** tool endpoints target **< ~150 ms** (indexed Postgres queries, no third-party calls in the hot path, connection pooling); **(b)** a **fast LLM tier** in Retell; **(c)** **small prompt** (§5) → fewer input tokens → faster first token.
- We **measure** end-to-end + component latency via Layer 3 and report **p50/p90**, not a single number.

---

## 9. Deployment

- Backend + Postgres on **Render or Railway** (public HTTPS URL for webhooks; `docker-compose` for local parity).
- Retell agent + phone number provisioned via API (`retell/deploy_agent.py`), pointed at the deployed webhook URL.
- Result: a **real phone number graders can call**, backed by a real DB.

---

## 10. Build milestones

1. Scraper → frozen real-data snapshot + provenance.
2. Backend: models, seed (+ slot generation), all tool endpoints, conflict/idempotency, signature verify.
3. Layer-1 tests green.
4. Retell agent: prompt + tool schemas, deploy script, first live call working.
5. Eval Layers 2 & 3 + report; run and commit `RESULTS.md`.
6. Deploy backend + agent; README + Loom script.

---

## 11. Known limitations (README, honest)

- Slots synthesized on top of real OPD schedules (doctors/departments are real).
- Frozen data snapshot (documented re-scrape path).
- No real payments/EHR/insurance; patient identity = phone number only.
- Eval text-layer misses audio-domain failures; Layer-3 samples are few.

## What I need from you (not blocking the plan)
- Retell + LLM API keys and a hosting choice (Render vs Railway) when we reach deploy.
- **Loom recording is yours to do** — I'll provide a shot-list + script.

## Verification (how we'll prove it works)
- `make test` → Layer-1 pytest green (conflict/idempotency proven).
- `make eval` → Layers 1–2 against the live backend; `eval/RESULTS.md` shows DB-verified task success across all scenarios incl. failure cases.
- **Live call** to the deployed Retell number completes a booking; the appointment appears in Postgres; Layer-3 report shows measured p50/p90 latency.
