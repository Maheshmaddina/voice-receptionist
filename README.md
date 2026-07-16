# Voice AI Receptionist — Fortis Memorial Research Institute, Gurgaon

A phone receptionist for a real hospital. Callers speak naturally and walk away
with an appointment **booked, rescheduled, or cancelled** against a real doctor
database — no human involved.

**Live demo:** call the number in the submission notes (Retell-hosted).
**Data:** 154 real doctors, 34 real departments, real designations/fees/experience,
scraped from the official [FMRI Gurgaon directory](https://www.fortishealthcare.com/doctors/hospital/fortis-memorial-research-institute-gurgaon)
— provenance and real-vs-synthesized boundary documented in [`data/PROVENANCE.md`](data/PROVENANCE.md).

## Architecture

```
Caller ──► Retell (STT · turn-taking · GPT-4.1 · TTS)
                │  custom-function webhooks (signed)
                ▼
        FastAPI backend (7 tool endpoints)
                │
                ▼
        Postgres — real doctors/departments, slot grid, appointments
```

- **`scraper/`** — Playwright scraper for the official Fortis directory (behind Cloudflare); output frozen in `data/`.
- **`backend/`** — tool endpoints: `find_doctors` (fuzzy), `search_availability`, `book/reschedule/cancel`, `lookup_appointments`, `get_clinic_info`.
- **`retell/`** — agent prompt (~400 tokens), tool schemas (single source of truth shared with the eval), idempotent deploy script.
- **`eval/`** — 3-layer harness; see [`eval/README.md`](eval/README.md) and committed results in [`eval/RESULTS.md`](eval/RESULTS.md).

## Key choices (and why)

**Retell over Bolna.** Retell owns the hardest voice problems — STT, endpointing,
barge-in, turn-taking — pre-tuned, plus hosted telephony, which makes the agent
independently callable with minimal glue. Bolna's self-hosting is the right call
for cost control at scale; wrong trade for building a reliable agent in 2–3 days.

**Retell-LLM + Custom Functions, not the custom-LLM WebSocket.** Self-hosting the
LLM loop adds a network hop and forfeits Retell's tuned orchestration. Our latency
budget goes where we control it: tool speed and prompt size.

**Failure handling lives in the backend, not the prompt.** Tools never return bare
errors — a conflict returns `alternatives`, an ambiguous name returns a
disambiguation list, an unknown department returns the real department list. The
agent always has a next step to speak. Double-booking is impossible by
construction (atomic conditional slot claim), and idempotency keys make Retell's
automatic webhook retries safe.

**Small prompt (~400 tokens).** Reasoning lives in tool results, not prompt prose.
Fewer input tokens → faster first token → snappier turns; less prose → less drift.

**Eval scores DB state, not vibes.** Every scenario ends with assertions against
the database: the right appointment exists or it doesn't. An LLM judge covers
groundedness and confirm-before-write as a secondary, advisory signal.

## Latency story

Retell's STT/TTS/turn-taking are pre-optimized; our levers are the ones we own:

1. **Tool endpoints** — indexed queries, no third-party calls in the hot path;
   measured p50 in Layer-2 runs (see `eval/RESULTS.md`).
2. **LLM tier** — GPT-4.1 with `model_high_priority` (dedicated capacity) and
   temperature 0.
3. **Prompt size** — ~400 tokens + 7 compact tool schemas.
4. **Measured, not claimed** — `eval/live/latency.py` pulls per-call e2e/LLM/TTS
   percentiles from real calls; the submission quotes p50/p90 from that report.

## Try it live (no setup)

- **Talk to the agent:** https://fmri-receptionist-backend.onrender.com/ — click *Call the receptionist* (browser voice call against the deployed agent + database).
- **See the booking you just made:** `curl "https://fmri-receptionist-backend.onrender.com/debug/appointments?phone=<your number>"`

## Run it

```bash
make setup                  # venv + deps
make serve                  # backend on :8000 (SQLite, auto-seeds) — or: docker compose up
make test                   # Layer 1: 14 deterministic invariant tests
make eval                   # Layer 2: simulated calls + judge → eval/RESULTS.md
```

Layer 2 needs any OpenAI-compatible LLM. The committed results used the Gemini
free tier (`GEMINI_API_KEY=... EVAL_MODEL=gemini-3.1-flash-lite make eval`);
`OPENAI_API_KEY=...` works too. A fully local option is
[Ollama](https://ollama.com) (`EVAL_API_KEY=ollama
EVAL_API_BASE=http://localhost:11434/v1 EVAL_MODEL=<model> make eval`), but
small local models (≤4B) are too weak to drive the booking flow reliably —
expect failures that are the model's, not the agent's.

Deploy: host the backend anywhere public (Dockerfile provided), then
`RETELL_API_KEY=... BACKEND_URL=https://... make deploy-agent` creates/updates the
Retell agent and binds the phone number.

## Known limitations

- **Slot grids are synthesized** on top of the real doctors (the public site
  doesn't expose per-doctor OPD calendars); doctors, departments, fees are real.
  ~35% of slots are pre-blocked so conflicts genuinely occur.
- **Frozen snapshot** (2026-07-15) keeps the repo runnable offline; `make scrape`
  re-pulls the live directory.
- **Patient identity is a phone number** — no OTP, no EHR, no payments.
- **Eval blind spots** — text-layer eval misses STT/accent/barge-in failures;
  Layer 3 covers them with a small sample. Details in `eval/README.md`.
- **Timezone** — all times are IST wall-clock; callers are assumed to be in India.
