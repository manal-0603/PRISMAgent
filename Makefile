# Common tasks. Run `make help` for the list. The Python commands use the virtual environment in .venv.

PY  := .venv/bin/python
BIN := .venv/bin

.DEFAULT_GOAL := help
.PHONY: help install install-web test lint typecheck check web serve demo quota

help:  ## list the tasks
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-12s %s\n", $$1, $$2}'

install:  ## create .venv and install the Python package with its development tools
	uv venv --python 3.12 --allow-existing
	uv pip install --python $(PY) -e ".[dev]"

install-web:  ## install the JavaScript packages of the web interface
	cd web && npm install --no-audit --no-fund

test:  ## run the tests (no network, no API key)
	$(PY) -m pytest -q

lint:  ## check the Python code with ruff
	$(BIN)/ruff check src tests

typecheck:  ## type-check the web interface
	cd web && npm run typecheck

check: lint test typecheck  ## everything the continuous integration runs

web:  ## start the web interface on http://localhost:3000
	$(BIN)/sysrev web

serve:  ## start the HTTP API alone on http://127.0.0.1:8000
	$(BIN)/sysrev serve

demo:  ## browse the demonstration review in the web interface (no API key needed)
	RUNS_DIR=examples $(BIN)/sysrev web

quota:  ## show the model quota used over the last 24 hours
	$(BIN)/sysrev quota
