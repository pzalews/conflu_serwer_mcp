.PHONY: install test lint typecheck format check run-stdio run-http docker-build docker-run clean

install:
	uv pip install -e ".[dev]"

test:
	python -m pytest tests/ -v

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/

check: lint typecheck test

run-stdio:
	python -m confluence_mcp

run-http:
	MCP_TRANSPORT=http MCP_HTTP_HOST=127.0.0.1 MCP_HTTP_PORT=8000 python -m confluence_mcp

docker-build:
	docker build -t confluence-server-mcp .

docker-run:
	docker compose up

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist
