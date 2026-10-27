# Backend

The backend is the FastAPI service for the Renewable Forecast application. It serves wind generation and forecast data, computes forecast-versus-outturn analytics, and provides the API contract consumed by the frontend.

## Stack

- Python 3.14+, managed with [uv](https://docs.astral.sh/uv/)
- FastAPI and Pydantic for HTTP endpoints and response validation
- SQLModel / SQLAlchemy and Alembic for PostgreSQL persistence and migrations
- Psycopg 3 as the PostgreSQL driver

## Local development

Use the repository-root [README](../README.md#start-locally) for the complete setup, including Docker, environment configuration, Elexon data import, and starting both frontend and backend.

For backend-only work, ensure the root `.env` has a valid `DATABASE_URL` and `FASTAPI_ENV=development`, and that PostgreSQL is running (`docker compose up -d db` from the repository root). From the repository root:

```bash
uv sync
cd backend
uv run bash scripts/prestart.sh
uv run fastapi dev
```

The API is served at <http://localhost:8000>. Interactive Swagger documentation is at <http://localhost:8000/docs>; the OpenAPI schema is at `/api/v1/openapi.json`.

`prestart.sh` applies pending Alembic migrations and runs `app/initial_data.py`. Initialization loads January 2026 data from `data/elexon/` when present; if normalized CSVs are absent, it invokes `scripts/elexon_history_import.py` to fetch and generate them. The data directory is Git-ignored. See the root README for the importer command and data notes.

## API areas

API routes are composed in `app/api/main.py` and mounted by `app/main.py`.

- `app/api/routes/wind.py`: actual generation, forecasts, dataset summary, and decision coverage.
- `app/api/routes/analytics.py`: overview, forecast/actual comparisons, accuracy metrics, forecast publication versions, and CSV export.
- `app/api/routes/utils.py`: health and utility endpoints.

The analytics routes use `app/services/wind_service.py`; the wind routes use `app/crud.py`. Shared request/response and database models are defined in `app/models.py`. API responses are derived from the FastAPI OpenAPI schema and consumed by the generated frontend client.

## Data initialization and migrations

The Elexon importer is at `../scripts/elexon_history_import.py`. To explicitly fetch/generate source CSVs, run this from the repository root:

```bash
python3 scripts/elexon_history_import.py
```

To run database initialization manually, from `backend/`:

```bash
uv run python app/initial_data.py
```

Check current data availability without importing:

```bash
uv run python app/initial_data.py --check-only
```

Force a reload from CSV/API data:

```bash
uv run python app/initial_data.py --force
```

When changing persisted models, add and commit an Alembic revision. From `backend/`:

```bash
uv run alembic revision --autogenerate -m "Describe schema change"
uv run alembic upgrade head
```

Review generated migrations before applying them; do not edit an already-applied migration to change schema history.

## Tests and quality checks

Run backend tests from `backend/`:

```bash
uv run bash scripts/test.sh
```

Tests are in `tests/`, organized around API routes, CRUD, services, and initialization. Importer tests are in the repository-level `scripts/tests/` directory and can be run from the root:

```bash
uv run pytest scripts/tests
```

If changing an API request or response, review the OpenAPI diff and regenerate the frontend client from the repository root:

```bash
bash scripts/generate-client.sh
```

## Backend layout

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app construction, middleware, router mounting, and serving built frontend assets when available. |
| `app/api/` | HTTP routes and dependency injection. |
| `app/services/` | Wind forecast matching and analytics logic. |
| `app/crud.py` | Database reads and writes. |
| `app/models.py` | SQLModel entities and API schemas. |
| `app/core/` | Settings and database engine configuration. |
| `app/alembic/` | Database migration history and Alembic environment. |
| `app/initial_data.py`, `app/wind_csv.py`, `app/init_db.py` | Data conversion, loading, migration orchestration, and validation. |
| `tests/` | Backend unit and API tests. |
| `scripts/` | Backend startup and test helpers. |
