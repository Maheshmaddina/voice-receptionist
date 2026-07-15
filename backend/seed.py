"""Seed the database from the frozen real-data snapshot (data/fortis_fmri_raw.json).

Doctors, departments, designations, fees: real, verbatim from the snapshot.
Slots: generated (documented in data/PROVENANCE.md) —
  - Each doctor gets 3 OPD weekdays + alternating Saturdays, chosen deterministically
    from a hash of their profile URL, within typical FMRI OPD blocks
    (09:30–13:00 and 17:00–19:30 IST), 30-minute grid, for the next SEED_DAYS days.
  - ~35% of slots are pre-marked 'blocked' (existing hospital load) with a seeded RNG,
    so "slot not available" conflicts genuinely occur.

Usage: python -m backend.seed [--days 14] [--fresh]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, time, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from backend.app.db import Base, SessionLocal, engine
from backend.app.logic import normalize, now_ist
from backend.app.models import Appointment, Department, Doctor, IdempotencyRecord, Patient, Slot

SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "fortis_fmri_raw.json"
OPD_BLOCKS = [(time(9, 30), time(13, 0)), (time(17, 0), time(19, 30))]
SLOT_MINUTES = 30
BLOCKED_RATIO = 0.35


def stable_hash(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def opd_weekdays(key: str) -> set[int]:
    """3 deterministic weekdays (Mon–Fri) + Saturday on alternate weeks."""
    h = stable_hash(key)
    days = {h % 5, (h // 7) % 5, (h // 49) % 5}
    filler = 0
    while len(days) < 3:  # collisions above can leave fewer than 3 distinct days
        days.add(filler % 5)
        filler += 1
    return days


def seed(days: int, fresh: bool) -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    snapshot = json.loads(SNAPSHOT.read_text())

    if fresh:
        for table in (Appointment, IdempotencyRecord, Slot, Patient, Doctor, Department):
            db.execute(delete(table))
        db.commit()

    if db.scalar(select(Doctor).limit(1)):
        print("DB already seeded — use --fresh to reset.")
        return

    dept_rows: dict[str, Department] = {}
    for rec in snapshot["doctors"]:
        for d in rec["departments"]:
            name = d["department"]
            if name not in dept_rows:
                dept_rows[name] = Department(name=name)
                db.add(dept_rows[name])

    doctors: list[Doctor] = []
    for rec in snapshot["doctors"]:
        doc = Doctor(
            name=rec["name"],
            normalized_name=normalize(rec["name"]),
            designation=rec.get("designation") or "",
            departments=" | ".join(d["department"] for d in rec["departments"]),
            specialties=" | ".join(s for d in rec["departments"] for s in d["specialties"]),
            experience_years=rec.get("experience_years"),
            consultation_fee_inr=rec.get("consultation_fee_inr"),
            profile_url=rec.get("profile_url"),
        )
        db.add(doc)
        doctors.append(doc)
    db.flush()

    rng = random.Random(42)
    today = now_ist().date()
    n_slots = 0
    for doc in doctors:
        key = doc.profile_url or doc.name
        weekdays = opd_weekdays(key)
        sat_parity = stable_hash(key) % 2
        for offset in range(1, days + 1):  # start tomorrow: today's past slots aren't useful
            day = today + timedelta(days=offset)
            wd = day.weekday()
            works = wd in weekdays or (wd == 5 and (day.isocalendar().week % 2) == sat_parity)
            if not works or wd == 6:  # OPD closed Sunday
                continue
            for block_start, block_end in OPD_BLOCKS:
                t = datetime.combine(day, block_start)
                end = datetime.combine(day, block_end)
                while t + timedelta(minutes=SLOT_MINUTES) <= end:
                    status = "blocked" if rng.random() < BLOCKED_RATIO else "open"
                    db.add(Slot(doctor_id=doc.id, start=t,
                                end=t + timedelta(minutes=SLOT_MINUTES), status=status))
                    n_slots += 1
                    t += timedelta(minutes=SLOT_MINUTES)
    db.commit()
    open_count = db.scalar(select(Slot).where(Slot.status == "open").limit(1))
    print(f"seeded {len(doctors)} doctors, {len(dept_rows)} departments, {n_slots} slots "
          f"(open slots exist: {bool(open_count)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()
    seed(args.days, args.fresh)
