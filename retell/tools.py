"""Custom-function tool definitions for the Retell LLM.

Single source of truth: the eval harness (text mode) and deploy_agent.py both
import TOOLS so the simulated agent and the live voice agent expose identical
tools against the same backend.
"""


def tool_defs(backend_url: str) -> list[dict]:
    u = backend_url.rstrip("/")

    def tool(name, description, params, required=None, speak_during=True):
        return {
            "type": "custom",
            "name": name,
            "description": description,
            "url": f"{u}/tools/{name}",
            "speak_during_execution": speak_during,
            "speak_after_execution": True,
            "parameters": {
                "type": "object",
                "properties": params,
                "required": required or [],
            },
        }

    return [
        tool(
            "get_clinic_info",
            "Hospital address, OPD hours, today's date, and the full list of departments.",
            {},
            speak_during=False,
        ),
        tool(
            "find_doctors",
            "Find doctors by (possibly misspelled) name and/or department. Returns id, designation, department, experience, and consultation fee.",
            {
                "query": {"type": "string", "description": "Doctor name as heard, e.g. 'doctor sandhu'"},
                "department": {"type": "string", "description": "Department or specialty, e.g. 'Cardiac Sciences', 'skin'"},
            },
        ),
        tool(
            "search_availability",
            "Open slots for a doctor. Prefer doctor_id from find_doctors. Returns slot_id + spoken time for each option, or nearest alternatives when the requested window is full.",
            {
                "doctor_id": {"type": "integer", "description": "Doctor id from find_doctors"},
                "doctor_name": {"type": "string", "description": "Fallback if no id yet"},
                "department": {"type": "string", "description": "Fallback department search"},
                "date_from": {"type": "string", "description": "ISO datetime lower bound, e.g. 2026-07-20T00:00:00"},
                "date_to": {"type": "string", "description": "ISO datetime upper bound"},
                "time_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening"]},
            },
        ),
        tool(
            "book_appointment",
            "Book a confirmed slot. Call only after the caller confirmed name, phone, slot, and type. On conflict returns alternatives.",
            {
                "slot_id": {"type": "integer", "description": "slot_id from search_availability"},
                "patient_name": {"type": "string"},
                "patient_phone": {"type": "string", "description": "10-digit mobile number"},
                "appointment_type": {"type": "string", "enum": ["new_consultation", "follow_up", "teleconsultation"]},
                "idempotency_key": {"type": "string", "description": "Random 8-char string, unique per booking action"},
            },
            required=["slot_id", "patient_name", "patient_phone", "appointment_type"],
        ),
        tool(
            "lookup_appointments",
            "Find the caller's upcoming appointments by their 10-digit phone number. Needed before reschedule or cancel.",
            {"patient_phone": {"type": "string", "description": "10-digit mobile number"}},
            required=["patient_phone"],
        ),
        tool(
            "reschedule_appointment",
            "Move an existing appointment to a new slot_id from search_availability. On conflict returns alternatives.",
            {
                "appointment_id": {"type": "integer"},
                "new_slot_id": {"type": "integer"},
                "idempotency_key": {"type": "string", "description": "Random 8-char string, unique per action"},
            },
            required=["appointment_id", "new_slot_id"],
        ),
        tool(
            "cancel_appointment",
            "Cancel an existing appointment after the caller confirms.",
            {
                "appointment_id": {"type": "integer"},
                "idempotency_key": {"type": "string", "description": "Random 8-char string, unique per action"},
            },
            required=["appointment_id"],
        ),
    ]
