sync:
	cd backend && uv sync --dev

test:
	cd backend && uv run pytest -q

api:
	cd backend && uv run uvicorn scout_email.app:app --reload --port 8000

verify-v1:
	bash scripts/verify_v1.sh
