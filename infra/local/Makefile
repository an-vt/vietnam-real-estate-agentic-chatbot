.PHONY: check-env up down logs restart bash test

check-env:
	@if [ ! -f .env ]; then echo "Missing file .env"; exit 1; fi

up: check-env
	docker compose --env-file .env -f docker-compose.yml up --build -d

down: check-env
	docker compose --env-file .env -f docker-compose.yml down

logs: check-env
	docker compose --env-file .env -f docker-compose.yml logs -f backend

restart: check-env
	docker compose --env-file .env -f docker-compose.yml restart ${t}

bash: check-env
	docker compose --env-file .env -f docker-compose.yml exec ${t} bash

test: check-env
	docker compose --env-file .env -f docker-compose.yml exec -T backend python -m unittest discover -s tests -v
	docker compose --env-file .env -f docker-compose.yml exec -T frontend npm run build
