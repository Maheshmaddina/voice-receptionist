PY := .venv/bin/python

.PHONY: setup scrape seed serve test eval eval-run eval-judge eval-report deploy-agent

setup:            ## venv + deps
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

scrape:           ## re-scrape the live FMRI directory (Playwright)
	.venv/bin/playwright install chromium
	$(PY) scraper/scrape_fmri.py

seed:             ## (re)seed DB from the frozen real-data snapshot
	$(PY) -m backend.seed --fresh

serve:            ## run backend on :8000 (seeds automatically if empty)
	$(PY) -m backend.seed || true
	$(PY) -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

test:             ## Layer 1: deterministic backend invariants
	$(PY) -m pytest backend/tests/ -q

eval: eval-run eval-judge eval-report   ## Layer 2 end-to-end

eval-run:
	$(PY) -m eval.runner

eval-judge:
	$(PY) -m eval.judge

eval-report:
	$(PY) -m eval.report

deploy-agent:     ## push prompt + tools to Retell (needs RETELL_API_KEY, BACKEND_URL)
	$(PY) retell/deploy_agent.py
