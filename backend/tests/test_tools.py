"""Layer-1 eval: deterministic integration tests of the booking backend.

Runs against a throwaway SQLite DB seeded from the real FMRI snapshot,
so every invariant is checked on the same data the live agent uses.
"""

import os
import tempfile

import pytest

TMPDIR = tempfile.mkdtemp(prefix="clinic-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{TMPDIR}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded():
    seed(days=10, fresh=True)


@pytest.fixture
def client():
    return TestClient(app)


def call(client, tool, **args):
    r = client.post(f"/tools/{tool}", json={"args": args})
    assert r.status_code == 200
    return r.json()


def first_doctor_and_slot(client, department="Cardiac"):
    doc = call(client, "find_doctors", department=department)["doctors"][0]
    slots = call(client, "search_availability", doctor_id=doc["doctor_id"])["slots"]
    assert slots, "seeded doctor must have open slots"
    return doc, slots


# ---------- data reality ----------

def test_seeded_from_real_snapshot(client):
    info = call(client, "get_clinic_info")
    assert "Fortis Memorial Research Institute" in info["name"]
    assert len(info["departments"]) >= 30
    docs = call(client, "find_doctors", department="Oncology")["doctors"]
    assert docs and all(d["name"].startswith("Dr") for d in docs)
    assert all(d["consultation_fee_inr"] for d in docs)


def test_fuzzy_doctor_match(client):
    # misspelled / partial names should still resolve
    r = call(client, "find_doctors", query="manjinder sandu")
    assert any("Sandhu" in d["name"] for d in r["doctors"])


def test_unknown_department_returns_recovery_data(client):
    r = call(client, "find_doctors", department="Astrology")
    assert "error" in r and "valid_departments" in r


# ---------- booking ----------

def test_book_and_double_book_conflict(client):
    doc, slots = first_doctor_and_slot(client)
    slot_id = slots[0]["slot_id"]
    booked = call(client, "book_appointment", slot_id=slot_id,
                  patient_name="Asha Verma", patient_phone="9000000001")
    assert booked["booked"] and booked["doctor"] == doc["name"]

    clash = call(client, "book_appointment", slot_id=slot_id,
                 patient_name="Rohan Gupta", patient_phone="9000000002")
    assert "error" in clash
    assert len(clash["alternatives"]) >= 1  # agent gets recovery options
    assert all(a["slot_id"] != slot_id for a in clash["alternatives"])


def test_idempotent_booking_replay(client):
    _, slots = first_doctor_and_slot(client, department="Urology")
    slot_id = slots[0]["slot_id"]
    kw = dict(slot_id=slot_id, patient_name="Meena Iyer", patient_phone="9000000003",
              idempotency_key="idem-book-1")
    first = call(client, "book_appointment", **kw)
    retry = call(client, "book_appointment", **kw)
    assert retry["appointment_id"] == first["appointment_id"]
    # and the patient has exactly one appointment
    r = client.get("/debug/appointments", params={"phone": "9000000003"}).json()
    assert len([a for a in r["appointments"] if a["status"] == "booked"]) == 1


def test_booking_requires_identity(client):
    _, slots = first_doctor_and_slot(client, department="Ophthalmology")
    r = call(client, "book_appointment", slot_id=slots[0]["slot_id"],
             patient_name="", patient_phone="12")
    assert "error" in r


def test_booking_nonexistent_slot(client):
    r = call(client, "book_appointment", slot_id=99999999,
             patient_name="Test", patient_phone="9000000000")
    assert "error" in r


# ---------- reschedule / cancel ----------

def test_reschedule_frees_old_slot_and_claims_new(client):
    doc, slots = first_doctor_and_slot(client, department="Dermatology")
    old, new = slots[0]["slot_id"], slots[1]["slot_id"]
    appt = call(client, "book_appointment", slot_id=old,
                patient_name="Kiran Rao", patient_phone="9000000004")
    moved = call(client, "reschedule_appointment",
                 appointment_id=appt["appointment_id"], new_slot_id=new)
    assert moved["rescheduled"]

    # old slot is bookable again; new slot conflicts
    rebook_old = call(client, "book_appointment", slot_id=old,
                      patient_name="Vikas Jain", patient_phone="9000000005")
    assert rebook_old.get("booked")
    rebook_new = call(client, "book_appointment", slot_id=new,
                      patient_name="Vikas Jain", patient_phone="9000000005")
    assert "error" in rebook_new


def test_reschedule_conflict_returns_alternatives(client):
    doc, slots = first_doctor_and_slot(client, department="Nephrology")
    a = call(client, "book_appointment", slot_id=slots[0]["slot_id"],
             patient_name="Patient A", patient_phone="9000000006")
    b = call(client, "book_appointment", slot_id=slots[1]["slot_id"],
             patient_name="Patient B", patient_phone="9000000007")
    r = call(client, "reschedule_appointment",
             appointment_id=a["appointment_id"], new_slot_id=slots[1]["slot_id"])
    assert "error" in r and r["alternatives"]


def test_cancel_releases_slot_and_is_idempotent(client):
    doc, slots = first_doctor_and_slot(client, department="Pulmonology")
    slot_id = slots[0]["slot_id"]
    appt = call(client, "book_appointment", slot_id=slot_id,
                patient_name="Sunil Kumar", patient_phone="9000000008")
    c1 = call(client, "cancel_appointment", appointment_id=appt["appointment_id"],
              idempotency_key="idem-cancel-1")
    c2 = call(client, "cancel_appointment", appointment_id=appt["appointment_id"],
              idempotency_key="idem-cancel-1")
    assert c1["cancelled"] and c2["cancelled"]
    rebook = call(client, "book_appointment", slot_id=slot_id,
                  patient_name="Next Patient", patient_phone="9000000009")
    assert rebook.get("booked")


# ---------- lookup / vague input ----------

def test_lookup_by_phone(client):
    r = call(client, "lookup_appointments", patient_phone="9000000001")
    assert r["appointments"] and r["patient"] == "Asha Verma"


def test_lookup_unknown_phone(client):
    r = call(client, "lookup_appointments", patient_phone="9999999999")
    assert r["appointments"] == []


def test_availability_disambiguates_department_search(client):
    r = call(client, "search_availability", department="Paediatrics")
    assert "disambiguate" in r and len(r["disambiguate"]) > 1


def test_availability_time_of_day_filter(client):
    doc = call(client, "find_doctors", department="Cardiac")["doctors"][0]
    r = call(client, "search_availability", doctor_id=doc["doctor_id"], time_of_day="evening")
    for s in r["slots"]:
        from datetime import datetime
        assert datetime.fromisoformat(s["start"]).hour >= 17
