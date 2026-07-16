# Eval Results

- **Ran:** 2026-07-16T13:49:23.608641+05:30  |  **Model (sim/judge):** gemini-3.1-flash-lite  |  **Backend:** http://localhost:8000
- **Task success (DB-verified): 9/9**

| Scenario | DB-verified | Turns | Tool calls | Tool p50 (ms) | Judge flags |
|---|---|---|---|---|---|
| simple_booking | ✅ PASS | 13 | 7 | 6.5 | 2 |
| vague_request | ✅ PASS | 13 | 4 | 10.6 | 1 |
| change_of_mind | ✅ PASS | 13 | 4 | 9.3 | 0 |
| conflict_sabotage | ✅ PASS | 15 | 4 | 10.2 | 0 |
| impossible_time | ✅ PASS | 7 | 3 | 9.9 | 1 |
| reschedule | ✅ PASS | 9 | 5 | 12.8 | 1 |
| cancel | ✅ PASS | 9 | 2 | 11.7 | 1 |
| unknown_doctor | ✅ PASS | 7 | 2 | 13.1 | 0 |
| wrong_phone_corrected | ✅ PASS | 11 | 7 | 6.6 | 2 |

## Failed checks / judge flags

- **simple_booking** [judge] Confirmation: did the agent read back name, phone, and slot and get a clear yes BEFORE any — The agent performed the booking tool call before confirming the patient's name and phone number.
- **simple_booking** [judge] Did the agent confirm the patient's name, phone number, and slot before booking? — The agent called the booking tool immediately after the patient agreed to the slot, only asking for the name and phone number after the booking was already processed.
- **vague_request** [judge] Confirmation: did the agent read back name, phone, and slot and get a clear yes BEFORE any — The agent performed the booking tool call before confirming the patient's name and phone number with the patient.
- **impossible_time** [judge] Confirmation: did the agent read back name, phone, and slot and get a clear yes BEFORE any — The agent performed the booking tool call before confirming the details with the patient.
- **reschedule** [judge] Confirmation: did the agent read back name, phone, and slot and get a clear yes BEFORE any — The agent did not read back the phone number or confirm the specific slot details with the patient before executing the reschedule tool call.
- **cancel** [judge] Confirmation: did the agent read back name, phone, and slot and get a clear yes BEFORE any — The agent read back the name and appointment slot, but did not read back the phone number before proceeding with the cancellation.
- **wrong_phone_corrected** [judge] Confirmation: did the agent read back name, phone, and slot and get a clear yes BEFORE any — The agent requested the phone number after the patient had already agreed to the slot, and the booking tool was called after the patient provided the number, but the agent did not perform a final confirmation of all details after the phone number was corrected.
- **wrong_phone_corrected** [judge] Did the agent use the corrected phone number in the final booking and read it back? — The agent used the correct phone number in the booking tool, but failed to read the final confirmed phone number back to the patient.

## Reading these numbers

- **DB-verified** is the primary signal: after the conversation, the database either
  contains exactly the right appointment (right patient, right department, right status) or it doesn't.
- **Judge flags** cover what DB state can't see: groundedness (no invented doctors/slots)
  and confirm-before-write behavior. LLM-judged, so treat as directional.
- **Tool p50** is backend HTTP latency as seen by the agent — the component of voice
  latency this repo owns. Full per-call latency (STT/LLM/TTS) comes from `eval/live/`.
