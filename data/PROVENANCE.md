# Data Provenance

## Source

**Fortis Memorial Research Institute (FMRI), Gurgaon** — official doctor directory on the
Fortis Healthcare website:

> https://www.fortishealthcare.com/doctors/hospital/fortis-memorial-research-institute-gurgaon

- **Scraped:** 2026-07-15 (UTC timestamp inside `fortis_fmri_raw.json`)
- **Method:** Playwright headless Chromium rendering (the site sits behind Cloudflare and
  403s plain HTTP clients), walking the Drupal pager (`?field_hospitals=3528&page=0..12`)
  and parsing the server-rendered `div.doctor_profile` cards.
- **Scraper:** `scraper/scrape_fmri.py` — re-run with `make scrape`.

## What is real vs. synthesized

**Real (verbatim from the official site):**
- 154 doctors: full name, designation, profile URL
- 34 departments and their sub-specialties per doctor
- Years of experience
- Consultation fee (INR)
- Hospital identity & address

**Synthesized (documented, on top of the real data):**
- **Bookable slot grids.** The public directory does not expose per-doctor OPD calendars,
  so `backend/seed.py` generates slots from a realistic OPD template (Mon–Sat, morning +
  evening blocks, appointment-type durations) attached to each real doctor. Doctors,
  departments, and fees are never invented.
- **Appointment types** (New Consultation / Follow-up / Teleconsultation) mirror the
  categories Fortis offers for online booking, with realistic durations.

## Why a frozen snapshot

`fortis_fmri_raw.json` is committed so that the repo runs offline, seeding is
deterministic, and the eval harness is reproducible. The data remains genuinely
real and re-scrapeable at any time via `make scrape`.
