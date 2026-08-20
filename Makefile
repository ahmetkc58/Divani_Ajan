.PHONY: setup backend frontend dev test lint synthetic docker-build docker-up docker-down

setup:
	cd backend && uv --cache-dir /private/tmp/evrakai-uv-cache sync --dev
	cd frontend && npm install

backend:
	cd backend && APP_PROJECT_ROOT="$(CURDIR)" OLLAMA_BASE_URL=http://127.0.0.1:11434 uv --cache-dir /private/tmp/evrakai-uv-cache run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && APP_PROJECT_ROOT="$(CURDIR)" uv --cache-dir /private/tmp/evrakai-uv-cache run pytest
	cd frontend && npm run test

lint:
	cd backend && uv --cache-dir /private/tmp/evrakai-uv-cache run ruff check app tests ../scripts
	cd frontend && npm run build

synthetic:
	python3 scripts/generate_synthetic_data.py

docker-build:
	docker build -f backend/Dockerfile -t evrakai-backend:local .
	docker build -f frontend/Dockerfile -t evrakai-frontend:local .

docker-up: docker-build
	docker compose up --no-build

docker-down:
	docker compose down
