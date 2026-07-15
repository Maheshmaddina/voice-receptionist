"""Domain logic shared by the tool endpoints: fuzzy matching, slot search,
atomic claiming, alternatives, and voice-friendly formatting."""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import Appointment, Doctor, Patient, Slot

IST = ZoneInfo("Asia/Kolkata")
APPOINTMENT_TYPES = {
    "new_consultation": {"label": "New Consultation", "minutes": 30},
    "follow_up": {"label": "Follow-up", "minutes": 15},
    "teleconsultation": {"label": "Teleconsultation", "minutes": 20},
}


def now_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def normalize(name: str) -> str:
    n = re.sub(r"\b(dr|prof|col|mrs|mr|ms)\b\.?", " ", (name or "").lower())
    return re.sub(r"[^a-z ]", " ", n).strip()


def spoken_dt(dt: datetime) -> str:
    """'Thursday, 16 July at 10:30 AM' — what the agent reads out."""
    return dt.strftime("%A, %-d %B at %-I:%M %p")


def find_doctors(db: Session, query: str | None = None, department: str | None = None, limit: int = 5) -> list[Doctor]:
    doctors = db.scalars(select(Doctor)).all()
    results = doctors
    if department:
        dep = normalize(department)
        results = [
            d for d in results
            if dep in normalize(d.departments) or dep in normalize(d.specialties)
        ]
    if query:
        q = normalize(query)
        scored = []
        for d in results:
            name = d.normalized_name
            if q == name:
                score = 1.0
            elif q in name or all(tok in name for tok in q.split()):
                score = 0.9
            else:
                score = difflib.SequenceMatcher(None, q, name).ratio()
            if score >= 0.55:
                scored.append((score, d))
        scored.sort(key=lambda x: -x[0])
        results = [d for _, d in scored]
    return results[:limit]


def open_slots(
    db: Session,
    doctor_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    time_of_day: str | None = None,  # morning | afternoon | evening
    limit: int = 6,
) -> list[Slot]:
    start = max(date_from or now_ist(), now_ist())
    conds = [Slot.doctor_id == doctor_id, Slot.status == "open", Slot.start >= start]
    if date_to:
        conds.append(Slot.start <= date_to)
    slots = db.scalars(select(Slot).where(*conds).order_by(Slot.start)).all()
    if time_of_day in ("morning", "afternoon", "evening"):
        lo, hi = {"morning": (6, 12), "afternoon": (12, 17), "evening": (17, 22)}[time_of_day]
        slots = [s for s in slots if lo <= s.start.hour < hi]
    return list(slots[:limit])


def claim_slot(db: Session, slot_id: int) -> bool:
    """Atomic conditional update — the single mechanism that makes double-booking
    impossible, including across concurrent calls: only one UPDATE can flip
    status 'open' → 'booked'."""
    res = db.execute(
        update(Slot).where(Slot.id == slot_id, Slot.status == "open").values(status="booked")
    )
    return res.rowcount == 1


def release_slot(db: Session, slot_id: int) -> None:
    db.execute(update(Slot).where(Slot.id == slot_id, Slot.status == "booked").values(status="open"))


def alternatives_near(db: Session, slot: Slot, limit: int = 3) -> list[Slot]:
    """Nearest open slots for the same doctor around a conflicting slot."""
    slots = db.scalars(
        select(Slot).where(
            Slot.doctor_id == slot.doctor_id, Slot.status == "open", Slot.start >= now_ist()
        )
    ).all()
    return sorted(slots, key=lambda s: abs((s.start - slot.start).total_seconds()))[:limit]


def get_or_create_patient(db: Session, name: str, phone: str) -> Patient:
    phone = re.sub(r"\D", "", phone or "")[-10:]
    patient = db.scalar(select(Patient).where(Patient.phone == phone))
    if patient:
        if name and normalize(name) != normalize(patient.name):
            patient.name = name  # caller corrected their name
        return patient
    patient = Patient(name=name, phone=phone)
    db.add(patient)
    db.flush()
    return patient


def slot_payload(s: Slot) -> dict:
    return {"slot_id": s.id, "start": s.start.isoformat(), "spoken": spoken_dt(s.start)}


def doctor_payload(d: Doctor) -> dict:
    return {
        "doctor_id": d.id,
        "name": d.name,
        "designation": d.designation,
        "departments": d.departments,
        "experience_years": d.experience_years,
        "consultation_fee_inr": d.consultation_fee_inr,
    }


def appointment_payload(a: Appointment) -> dict:
    return {
        "appointment_id": a.id,
        "doctor": a.doctor.name,
        "start": a.slot.start.isoformat(),
        "spoken": spoken_dt(a.slot.start),
        "type": APPOINTMENT_TYPES.get(a.appointment_type, {}).get("label", a.appointment_type),
        "status": a.status,
        "patient": a.patient.name,
    }
