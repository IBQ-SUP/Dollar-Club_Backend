Trading Strategy Hub - Backend
================================

Stack: FastAPI, Celery, PostgreSQL, Redis, SQLAlchemy 2.0 (async), Alembic

Quickstart (Docker)
-------------------
1) Copy `.env.example` to `.env` and adjust values.
2) Build and run:
   - `docker compose up --build`
3) Apply migrations:
   - `docker compose exec api alembic upgrade head`
4) Open API docs:
   - http://localhost:8000/docs
5) Flower (Celery UI):
   - http://localhost:5555

Local Dev
---------
- Create virtualenv and `pip install -r requirements.txt`
- Run API: `uvicorn main:app --reload`
- Run worker: `celery -A app.celery_app.celery_app worker --loglevel=INFO`

Key Endpoints
-------------
- `POST /auth/register` — create user
- `POST /auth/login` — get JWT
- `GET /users/me` — current user
- `POST /bots` — create bot
- `GET /bots` — list bots
- `POST /backtests` — enqueue backtest
- `GET /backtests` — list backtests
- `GET /trades` — list trades across user bots

Architecture
------------
- `app/models` — SQLAlchemy models
- `app/schemas` — Pydantic models
- `app/api/routes` — API routers
- `app/tasks` — Celery tasks (backtests)
- `app/services` — backtesting engine boilerplate
- `app/db` — async session and base
- `alembic` — migrations

Notes
-----
- Replace `SimpleBacktester` with a real engine.
- Add role-based auth, rate limiting, observability (OpenTelemetry) for production.

