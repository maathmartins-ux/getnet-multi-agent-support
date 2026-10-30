.PHONY: install run test evals docker-up docker-test lint ingest
install:
	pip install -r requirements-dev.txt && pip install -e .
run:
	uvicorn getnet_agents.api:app --reload --port 8000
test:
	pytest -q
evals:
	python -m evals.run_evals
lint:
	ruff check src tests
docker-up:
	docker compose up --build
docker-test:
	docker compose --profile test run --rm tests
ingest:
	python -m getnet_agents.rag.ingest --urls data/knowledge/urls.txt --out data/knowledge/raw
