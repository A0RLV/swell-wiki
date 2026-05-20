.PHONY: install test smoke mcp-config ingest-once clean

VENV := .venv/bin

install:
	pip install -e '.[dev]'

test:
	$(VENV)/python -m pytest tests/ -v

smoke:
	$(VENV)/python tests/smoke.py

mcp-config:
	@test -n "$(WORKSPACE)" || (echo "Usage: make mcp-config WORKSPACE=/path/to/ws" && exit 1)
	./growth-cloud mcp-config $(WORKSPACE)

ingest-once:
	@test -n "$(WORKSPACE)" || (echo "Usage: make ingest-once WORKSPACE=/path/to/ws" && exit 1)
	./growth-cloud ingest $(WORKSPACE) --once

clean:
	rm -rf __pycache__ **/__pycache__ .pytest_cache *.egg-info dist build
