PY ?= .venv/bin/python
.PHONY: install seed index-examples backend frontend test eval eval-selftest

install:
	@# Python 3.11/3.12 recommended (some pinned wheels lack 3.14 builds)
	(command -v uv >/dev/null && uv venv --python 3.12 .venv && uv pip install --python $(PY) -r backend/requirements.txt) || (python3.12 -m venv .venv && $(PY) -m pip install -r backend/requirements.txt)
	cd frontend && npm install

seed:
	cd backend && ../$(PY) data/seed_db.py

index-examples:
	cd backend && ../$(PY) -m app.services.examples_manager --reindex

backend:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && ../$(PY) -m pytest -q

eval:
	cd backend && ../$(PY) eval/run_eval.py

# Harness plumbing check with an oracle "LLM" (returns ground truth) - NOT model results
eval-selftest:
	cd backend && ../$(PY) eval/run_eval.py --mock-oracle --output-dir ../reports --name selftest_report
