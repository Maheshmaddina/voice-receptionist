"""ORM models. All clinical entities come from the real FMRI Gurgaon snapshot;
slots are generated on top of the real doctors (see data/PROVENANCE.md)."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Doctor(Base):
    __tablename__ = "doctors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    normalized_name: Mapped[str] = mapped_column(String(160), index=True)
    designation: Mapped[str] = mapped_column(Text, default="")
    departments: Mapped[str] = mapped_column(Text)  # " | "-joined real department names
    specialties: Mapped[str] = mapped_column(Text, default="")  # " | "-joined sub-specialties
    experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consultation_fee_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    slots: Mapped[list["Slot"]] = relationship(back_populates="doctor")


class Slot(Base):
    """A 30-minute bookable unit. status: open | booked | blocked (pre-filled load)."""

    __tablename__ = "slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    start: Mapped[datetime] = mapped_column(DateTime, index=True)  # naive IST
    end: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    doctor: Mapped[Doctor] = relationship(back_populates="slots")
    __table_args__ = (UniqueConstraint("doctor_id", "start", name="uq_doctor_start"),)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(24), index=True)


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    appointment_type: Mapped[str] = mapped_column(String(40))  # new_consultation | follow_up | teleconsultation
    status: Mapped[str] = mapped_column(String(12), default="booked", index=True)  # booked | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    slot: Mapped[Slot] = relationship()
    doctor: Mapped[Doctor] = relationship()
    patient: Mapped[Patient] = relationship()


class IdempotencyRecord(Base):
    """Stores the first response for a mutating call so Retell's automatic retries
    (up to 2x on failure/timeouts) can never double-book or double-cancel."""

    __tablename__ = "idempotency"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


Index("ix_appt_patient_status", Appointment.patient_id, Appointment.status)
