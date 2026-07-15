"""Tool endpoints called by the Retell agent as Custom Functions.

Conventions:
- Every response is HTTP 200 with a compact JSON body the LLM can speak from.
  Domain problems come back as {"error": "..."} plus recovery data (alternatives,
  disambiguation lists) — never a bare 4xx/5xx, which Retell would treat as a
  failed call and blindly retry.
- Mutating endpoints accept an idempotency_key; retried calls replay the stored
  first response instead of re-executing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import logic
from .db import get_db
from .logic import APPOINTMENT_TYPES, now_ist
from .models import Appointment, Department, Doctor, IdempotencyRecord, Patient, Slot

router = APIRouter()

CLINIC = {
    "name": "Fortis Memorial Research Institute, Gurgaon",
    "address": "Sector 44, opposite HUDA City Centre, Gurugram, Haryana 122002",
    "opd_hours": "Monday to Saturday, 9:30 AM to 1 PM and 5 PM to 7:30 PM",
}


async def tool_args(request: Request) -> dict:
    """Accept both Retell payload shapes: {name, call, args} or bare args."""
    body = await request.json()
    return body.get("args", body) if isinstance(body, dict) else {}


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def idempotent(db: Session, key: str | None):
    if not key:
        return None
    rec = db.get(IdempotencyRecord, key)
    return json.loads(rec.response_json) if rec else None


def remember(db: Session, key: str | None, response: dict) -> dict:
    if key:
        db.merge(IdempotencyRecord(key=key, response_json=json.dumps(response)))
    return response


@router.post("/tools/get_clinic_info")
async def get_clinic_info(request: Request, db: Session = Depends(get_db)):
    departments = [d.name for d in db.scalars(select(Department).order_by(Department.name))]
    return {**CLINIC, "today": logic.spoken_dt(now_ist()), "departments": departments}


@router.post("/tools/find_doctors")
async def find_doctors(request: Request, db: Session = Depends(get_db)):
    args = await tool_args(request)
    query, department = args.get("query"), args.get("department")
    if not query and not department:
        return {"error": "Provide a doctor name or a department to search."}
    matches = logic.find_doctors(db, query, department)
    if not matches and department:
        # unknown department name — help the agent recover with the real list
        departments = [d.name for d in db.scalars(select(Department))]
        return {"error": f"No doctors matched department '{department}'.",
                "valid_departments": sorted(departments)}
    if not matches:
        return {"error": f"No doctor at FMRI matched '{query}'. Ask the caller to spell the name, or search by department."}
    return {"doctors": [logic.doctor_payload(d) for d in matches],
            "note": "multiple matches — ask the caller to choose" if len(matches) > 1 else None}


@router.post("/tools/search_availability")
async def search_availability(request: Request, db: Session = Depends(get_db)):
    args = await tool_args(request)
    doctor_id = args.get("doctor_id")
    date_from, date_to = parse_dt(args.get("date_from")), parse_dt(args.get("date_to"))
    time_of_day = args.get("time_of_day")

    if not doctor_id and (args.get("doctor_name") or args.get("department")):
        matches = logic.find_doctors(db, args.get("doctor_name"), args.get("department"), limit=3)
        if len(matches) == 1:
            doctor_id = matches[0].id
        elif matches:
            return {"disambiguate": [logic.doctor_payload(d) for d in matches],
                    "note": "ask the caller which doctor, then search again with doctor_id"}
        else:
            return {"error": "No matching doctor found. Use find_doctors first."}
    if not doctor_id:
        return {"error": "doctor_id (or doctor_name/department) is required."}

    doctor = db.get(Doctor, int(doctor_id))
    if not doctor:
        return {"error": f"No doctor with id {doctor_id}."}
    if date_from and date_from < now_ist() - timedelta(hours=1) and not date_to:
        # caller asked for a past date; roll forward instead of erroring
        date_from = None
    slots = logic.open_slots(db, doctor.id, date_from, date_to, time_of_day)
    if not slots:
        fallback = logic.open_slots(db, doctor.id, None, None, None, limit=3)
        return {"doctor": doctor.name, "slots": [],
                "message": "No open slots in that window.",
                "nearest_available": [logic.slot_payload(s) for s in fallback]}
    return {"doctor": doctor.name, "slots": [logic.slot_payload(s) for s in slots]}


@router.post("/tools/book_appointment")
async def book_appointment(request: Request, db: Session = Depends(get_db)):
    args = await tool_args(request)
    replay = idempotent(db, args.get("idempotency_key"))
    if replay:
        return replay

    slot_id = args.get("slot_id")
    name, phone = (args.get("patient_name") or "").strip(), (args.get("patient_phone") or "").strip()
    appt_type = args.get("appointment_type", "new_consultation")
    if not slot_id:
        return {"error": "slot_id is required — offer slots from search_availability first."}
    if not name or len(phone) < 10:
        return {"error": "Patient full name and a 10-digit phone number are required before booking."}
    if appt_type not in APPOINTMENT_TYPES:
        return {"error": f"appointment_type must be one of {list(APPOINTMENT_TYPES)}."}

    slot = db.get(Slot, int(slot_id))
    if not slot:
        return {"error": f"Slot {slot_id} does not exist. Search availability again."}
    if slot.start < now_ist():
        return {"error": "That slot is in the past. Search availability again."}

    if not logic.claim_slot(db, slot.id):
        alts = logic.alternatives_near(db, slot)
        db.commit()
        return {"error": "That slot was just taken.",
                "alternatives": [logic.slot_payload(s) for s in alts]}

    patient = logic.get_or_create_patient(db, name, phone)
    appt = Appointment(slot_id=slot.id, doctor_id=slot.doctor_id, patient_id=patient.id,
                       appointment_type=appt_type)
    db.add(appt)
    db.flush()
    response = {"booked": True, **logic.appointment_payload(appt),
                "fee_inr": slot.doctor.consultation_fee_inr}
    remember(db, args.get("idempotency_key"), response)
    db.commit()
    return response


@router.post("/tools/lookup_appointments")
async def lookup_appointments(request: Request, db: Session = Depends(get_db)):
    args = await tool_args(request)
    phone = "".join(c for c in (args.get("patient_phone") or "") if c.isdigit())[-10:]
    if len(phone) < 10:
        return {"error": "A 10-digit phone number is required to look up appointments."}
    patient = db.scalar(select(Patient).where(Patient.phone == phone))
    if not patient:
        return {"appointments": [], "message": "No appointments found for that number."}
    appts = db.scalars(
        select(Appointment).where(Appointment.patient_id == patient.id,
                                  Appointment.status == "booked")
    ).all()
    upcoming = [a for a in appts if a.slot.start >= now_ist()]
    return {"patient": patient.name,
            "appointments": [logic.appointment_payload(a) for a in sorted(upcoming, key=lambda a: a.slot.start)]}


@router.post("/tools/reschedule_appointment")
async def reschedule_appointment(request: Request, db: Session = Depends(get_db)):
    args = await tool_args(request)
    replay = idempotent(db, args.get("idempotency_key"))
    if replay:
        return replay

    appt_id, new_slot_id = args.get("appointment_id"), args.get("new_slot_id")
    if not appt_id or not new_slot_id:
        return {"error": "appointment_id and new_slot_id are required."}
    appt = db.get(Appointment, int(appt_id))
    if not appt or appt.status != "booked":
        return {"error": f"No active appointment with id {appt_id}. Use lookup_appointments."}
    new_slot = db.get(Slot, int(new_slot_id))
    if not new_slot:
        return {"error": f"Slot {new_slot_id} does not exist. Search availability again."}
    if new_slot.start < now_ist():
        return {"error": "That slot is in the past. Search availability again."}

    if not logic.claim_slot(db, new_slot.id):
        alts = logic.alternatives_near(db, new_slot)
        db.commit()
        return {"error": "That new slot was just taken.",
                "alternatives": [logic.slot_payload(s) for s in alts]}

    logic.release_slot(db, appt.slot_id)
    appt.slot_id = new_slot.id
    appt.doctor_id = new_slot.doctor_id
    db.flush()
    db.refresh(appt)
    response = {"rescheduled": True, **logic.appointment_payload(appt)}
    remember(db, args.get("idempotency_key"), response)
    db.commit()
    return response


@router.post("/tools/cancel_appointment")
async def cancel_appointment(request: Request, db: Session = Depends(get_db)):
    args = await tool_args(request)
    replay = idempotent(db, args.get("idempotency_key"))
    if replay:
        return replay

    appt_id = args.get("appointment_id")
    if not appt_id:
        return {"error": "appointment_id is required. Use lookup_appointments first."}
    appt = db.get(Appointment, int(appt_id))
    if not appt:
        return {"error": f"No appointment with id {appt_id}."}
    if appt.status == "cancelled":
        response = {"cancelled": True, "appointment_id": appt.id, "note": "was already cancelled"}
        remember(db, args.get("idempotency_key"), response)
        db.commit()
        return response

    appt.status = "cancelled"
    logic.release_slot(db, appt.slot_id)
    response = {"cancelled": True, **logic.appointment_payload(appt)}
    remember(db, args.get("idempotency_key"), response)
    db.commit()
    return response


# ---- eval support: reset transactional state (demo data only — doctors/slots stay) ----
@router.post("/debug/reset")
async def debug_reset(db: Session = Depends(get_db)):
    from sqlalchemy import delete, update as sql_update

    n = db.execute(delete(Appointment)).rowcount
    db.execute(delete(Patient))
    db.execute(delete(IdempotencyRecord))
    # reopen slots claimed by bookings; seeded 'blocked' slots stay blocked
    db.execute(sql_update(Slot).where(Slot.status == "booked").values(status="open"))
    db.commit()
    return {"reset": True, "appointments_deleted": n}


# ---- ground-truth reader for the eval harness & demos (demo data only) ----
@router.get("/debug/appointments")
async def debug_appointments(phone: str, db: Session = Depends(get_db)):
    digits = "".join(c for c in phone if c.isdigit())[-10:]
    patient = db.scalar(select(Patient).where(Patient.phone == digits))
    if not patient:
        return {"appointments": []}
    appts = db.scalars(select(Appointment).where(Appointment.patient_id == patient.id)).all()
    return {"patient": patient.name,
            "appointments": [
                {**logic.appointment_payload(a), "doctor_departments": a.doctor.departments}
                for a in appts
            ]}
