.PHONY: check-env up down logs

check-env:
	@if [ ! -f .env ]; then echo "Missing file .env"; exit 1; fi

up: check-env
	docker compose --env-file .env -f docker-compose.yml up --build -d

down: check-env
	docker compose --env-file .env -f docker-compose.yml down

logs: check-env
	docker compose --env-file .env -f docker-compose.yml logs -f backend
