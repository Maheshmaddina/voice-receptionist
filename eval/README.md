# Eval Harness

Three layers, cheapest-to-run first. Layers 1–2 are fully re-runnable by anyone
with the repo + any OpenAI-compatible LLM key (Gemini's free tier works);
Layer 3 needs a Retell key and real calls.

| Layer | What it tests | Command | Needs |
|---|---|---|---|
| 1 | Booking-engine invariants (deterministic pytest) | `make test` | nothing |
| 2 | Full conversations: simulated patient ↔ the real agent brain + live tools | `make eval` | any OpenAI-compatible LLM (free local option: Ollama `qwen3:4b`), running backend |
| 2.5 | Scripted conversation through the **deployed** Retell brain (server-side GPT-4.1 + live webhooks), verified in the production DB | `python -m eval.live.chat_smoke` | `RETELL_API_KEY` |
| 3 | Real voice calls: measured e2e/LLM/TTS latency + transcripts | `python -m eval.live.latency` | `RETELL_API_KEY`, a few live calls |

## What "performs well" means here, and why

**1. Task success, verified against the database (primary).**
A receptionist has exactly one job: after the call, the right appointment exists
(or doesn't). Every scenario ends with assertions against `/debug/appointments`
— right patient, right department, right status, right count. This can't be
gamed by a fluent transcript: if the agent *said* "you're booked" but no row
exists, the scenario fails. Transcript-only evals miss exactly this failure.

**2. Robustness under things going wrong (scenario design).**
The scenario set is weighted toward failure and mess, because that's where
voice agents die: a rival caller steals the offered slot mid-conversation
(injected deterministically via `sabotage`), a demanded time that never exists,
a mid-call change of mind, a corrected phone number, a doctor who doesn't work
at the hospital. Happy-path booking is 2 of 9 scenarios.

**3. Groundedness + confirm-before-write (LLM judge, secondary).**
DB state can't see whether the agent invented a doctor it never booked, or
wrote to the DB without reading back details. The judge audits the transcript
*against the tool log* for exactly those two properties, plus per-scenario
questions. Judge output is directional, never the pass/fail signal.

**4. Latency (measured, not asserted).**
Layer 2 measures backend tool latency (the part this repo owns); Layer 3 pulls
Retell's measured e2e/LLM/TTS percentiles from real calls. We report p50/p90.

## Why Layer 2 is text, not audio

The agent brain — prompt, tool schemas, tool endpoints, booking logic — is
identical between the text sim and the live voice agent (`eval/runner.py`
imports `retell/tools.py`; the prompt file is shared). Swapping the audio layer
for text makes the eval cheap, fast, and re-runnable in CI, which the
assignment requires. What text can't cover is listed below, honestly.

## Where this harness falls short

- **No audio-domain failures in Layers 1–2**: STT misrecognition (Indian names
  and phone digits are the risky ones), barge-in, accents, background noise.
  Only Layer 3 touches these, with a small sample size.
- **Model mismatch**: the text sim runs the prompt on whatever eval model you
  configure (default Gemini Flash); the live agent runs it on GPT-4.1 inside
  Retell. Prompt/tool/backend logic is shared, but model-specific tool-calling
  quirks may differ.
- **LLM judge variance**: judge verdicts can flip between runs; that's why DB
  state is the pass/fail signal and the judge is advisory.
- **Simulated patients are polite**: they follow their persona; real callers
  interrupt, mumble, and go silent. Interruption handling is delegated to
  Retell's turn-taking layer and only observed in Layer 3.
- **Time-relative data**: slots are seeded for the next 14 days; a stale DB
  (seeded weeks ago) empties availability. `make seed` refreshes.

## Running it

```bash
make serve          # terminal 1: backend on :8000 (seeds if needed)
make eval           # terminal 2: runner + judge + report
cat eval/RESULTS.md
```

`EVAL_MODEL` overrides the simulator/judge model (default `gemini-2.5-flash`
with a Gemini key; see `eval/llm.py` for the resolution order).
Scenario transcripts and full tool logs land in `eval/results/`.
