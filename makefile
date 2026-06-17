ub:
	docker compose -f docker-compose.yml up --build

u:
	docker compose -f docker-compose.yml up

ubd:
	docker compose -f docker-compose.yml up --build -d

ud:
	docker compose -f docker-compose.yml up -d

d:
	docker compose -f docker-compose.yml down

dv:
	docker compose -f docker-compose.yml down -v

bash:
	docker compose -f docker-compose.yml exec bot bash

db-bash:
	docker compose -f docker-compose.yml exec db bash