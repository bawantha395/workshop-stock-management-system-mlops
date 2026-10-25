.PHONY: configure model up down test frontend
configure:
	python3 scripts/configure_local.py
model:
	python3 scripts/download_model.py
up:
	docker compose up --build -d
down:
	docker compose down
test:
	mvn -B -ntp test
	PYTHONPATH=services/vision pytest services/vision/tests -q
frontend:
	cd apps/web && npm ci && npm run build
