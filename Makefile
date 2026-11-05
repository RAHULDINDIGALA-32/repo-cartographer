start-db:
	docker compose up -d postgres
stop-db:
	docker compose down
db-migrate:
	cd backend && uv run cartographer db migrate
db-reset:
	cd backend && uv run cartographer db reset --confirm
test:
	cd backend && uv run pytest
lint:
	cd backend && uv run ruff check .
