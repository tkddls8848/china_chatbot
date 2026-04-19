.PHONY: dev bot lint format test migrate makemigrations

dev:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

bot:
	python -m src.bot.main

lint:
	ruff check src/

format:
	ruff format src/

test:
	pytest tests/ -v

migrate:
	alembic upgrade head

makemigrations:
	alembic revision --autogenerate -m "$(msg)"
