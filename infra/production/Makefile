.PHONY: check check-env check-secrets config up down restart logs migrate ingest

COMPOSE = docker compose --env-file .env -f docker-compose.yml
CSV_PATH ?= $(shell sed -n 's/^CSV_PATH=//p' .env)
INGEST_BATCH_SIZE ?= $(or $(shell sed -n 's/^INGEST_BATCH_SIZE=//p' .env),512)

ifdef FORCE
INGEST_FLAGS = --force
else
INGEST_FLAGS =
endif

check-env:
	@test -f .env || (echo "Missing file .env"; exit 1)

check-secrets:
	@test -s secrets/postgres_password || (echo "Missing secrets/postgres_password"; exit 1)
	@test -s secrets/llm_api_key || (echo "Missing secrets/llm_api_key"; exit 1)

check: check-env check-secrets config

config:
	@$(COMPOSE) config --quiet

up: check
	$(COMPOSE) up --build -d
	$(COMPOSE) run --rm backend alembic upgrade head

down: check-env
	$(COMPOSE) down

restart: check-env
	$(COMPOSE) restart

logs: check-env
	$(COMPOSE) logs -f

migrate: check
	$(COMPOSE) run --rm backend alembic upgrade head

ingest: check
	@test -n "$(CSV_PATH)" || (echo "CSV_PATH is required in .env or on the make command line"; exit 1)
	@test -f "$(CSV_PATH)" || (echo "CSV file not found: $(CSV_PATH)"; exit 1)
	$(COMPOSE) run --rm -T -v "$(CSV_PATH):/data/input.csv:ro" backend \
		python -m src.script.ingest_csv \
		--csv /data/input.csv \
		--batch-size $(INGEST_BATCH_SIZE) \
		$(INGEST_FLAGS)
