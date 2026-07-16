# SkyMaster Backend v0.1

FastAPI backend for the SkyMaster drone platform (MVP).

## Quick start
1. `cp .env.example .env` and fill in secrets.
2. `pip install -e .` (Python 3.11+).
3. `alembic upgrade head` to apply migrations, then `uvicorn app.main:app --reload` to run the API on http://localhost:8000.
