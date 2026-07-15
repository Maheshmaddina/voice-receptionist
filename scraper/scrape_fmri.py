"""Scrape the real doctor directory of Fortis Memorial Research Institute (FMRI), Gurgaon
from the official Fortis Healthcare website.

fortishealthcare.com sits behind Cloudflare and 403s plain HTTP clients, so we render
pages with Playwright Chromium (which passes the check) and parse the server-rendered
Drupal doctor cards.

Output: data/fortis_fmri_raw.json  — one record per doctor with name, designation,
departments, sub-specialties, years of experience, consultation fee, and profile URL.

Usage:  python scraper/scrape_fmri.py [--out data/fortis_fmri_raw.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://www.fortishealthcare.com"
# field_hospitals=3528 is the Drupal term id for FMRI Gurgaon (visible in the pager links)
LIST_URL = BASE + "/doctors/hospital/fortis-memorial-research-institute-gurgaon?field_hospitals=3528&page={page}"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    doctors = []
    for card in soup.select("div.doctor_profile"):
        name_el = card.select_one(".doctor_name")
        if not name_el:
            continue
        link = card.select_one("a[href*='/doctors/dr-']")
        desig_el = card.select_one(".doctor_designation")
        designation, hospital = "", ""
        if desig_el:
            parts = [clean(p) for p in desig_el.get_text().split("|")]
            designation = parts[0] if parts else ""
            hospital = parts[1] if len(parts) > 1 else ""

        # departments: <li><b>Department</b> | sub-spec | sub-spec ...</li>
        departments = []
        for li in card.select(".doctor_specialities li"):
            b = li.find("b")
            dept = clean(b.get_text()) if b else ""
            subs = [clean(s) for s in li.get_text().split("|")]
            subs = [s for s in subs if s and s != dept]
            if dept:
                departments.append({"department": dept, "specialties": sorted(set(subs))})

        info_text = card.select_one(".doctor_imp_info")
        exp_years, fee = None, None
        if info_text:
            t = clean(info_text.get_text(" "))
            m = re.search(r"(\d+)\s*Years?", t)
            if m:
                exp_years = int(m.group(1))
            m = re.search(r"(\d[\d,]*)\s*Fees", t)
            if m:
                fee = int(m.group(1).replace(",", ""))

        doctors.append(
            {
                "name": clean(name_el.get_text()),
                "designation": designation,
                "hospital": hospital or "FMRI Gurgaon",
                "departments": departments,
                "experience_years": exp_years,
                "consultation_fee_inr": fee,
                "profile_url": BASE + link["href"] if link else None,
            }
        )
    return doctors


def last_page(html: str) -> int:
    # hrefs appear as "?field_hospitals=3528&amp;page=N" in raw HTML, so match loosely
    pages = re.findall(r"[?&;]page=(\d+)", html)
    return max(int(p) for p in pages) if pages else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/fortis_fmri_raw.json")
    args = ap.parse_args()

    all_doctors: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900}, locale="en-US")
        page = ctx.new_page()

        pg, max_pg = 0, 0
        while pg <= max_pg:
            url = LIST_URL.format(page=pg)
            print(f"fetching page {pg} …", file=sys.stderr)
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if not resp or resp.status != 200:
                raise RuntimeError(f"page {pg} returned {resp.status if resp else 'no response'}")
            page.wait_for_selector("div.doctor_profile", timeout=30000)
            html = page.content()
            batch = parse_cards(html)
            print(f"  {len(batch)} doctors", file=sys.stderr)
            all_doctors.extend(batch)
            max_pg = max(max_pg, last_page(html))
            pg += 1
        browser.close()

    # de-dupe by profile URL (a doctor can appear once per page overlap)
    seen, unique = set(), []
    for d in all_doctors:
        key = d["profile_url"] or d["name"]
        if key not in seen:
            seen.add(key)
            unique.append(d)

    snapshot = {
        "source": "https://www.fortishealthcare.com/doctors/hospital/fortis-memorial-research-institute-gurgaon",
        "hospital": "Fortis Memorial Research Institute, Gurgaon",
        "address": "Sector 44, Opposite HUDA City Centre, Gurugram, Haryana 122002, India",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "method": "Playwright Chromium rendering of the official Drupal doctor directory",
        "doctor_count": len(unique),
        "doctors": unique,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"wrote {len(unique)} doctors → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
