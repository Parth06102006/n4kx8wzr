# Frontend

The frontend is the Renewable Forecast dashboard. It presents UK wind forecast and actual generation data and provides learner/analyst views, date-range exploration, forecast revision context, and chart-based comparisons.

## Stack

- [Bun](https://bun.sh/) for workspace/package management and scripts
- [Vite](https://vite.dev/) for local development and production builds
- [React](https://react.dev/) and TypeScript
- TanStack Query for API data fetching/caching
- Recharts for visualizations, Tailwind CSS for styling, and shared Radix-based UI components
- Playwright for end-to-end browser tests; Biome for linting/formatting checks

## Local development

Use the repository-root [README](../README.md#start-locally) for the full-stack startup instructions. The frontend expects the FastAPI backend to be available at `http://localhost:8000`.

From the repository root, install workspace dependencies:

```bash
bun install
```

Create `frontend/.env` (Git-ignored) with the API base URL for local development:

```dotenv
VITE_API_URL=http://localhost:8000
```

With the backend running, start Vite from `frontend/`:

```bash
cd frontend
bun run dev
```

Open <http://localhost:5173>. To build the frontend, run `bun run build` from `frontend/`. In the normal deployment configuration Vite builds to `frontend/dist`; for the combined backend/Docker build it writes assets to `backend/app/frontend`, where FastAPI serves them.

## API client

Typed client code is generated from the backend's OpenAPI schema and lives in `src/client/`. The higher-level forecast hooks and API use are in `src/hooks/useRenewableForecast.ts` and `src/api/forecastApi.ts`.

After changing backend API request/response schemas, start the backend and regenerate the client from the repository root:

```bash
bash scripts/generate-client.sh
```

Review the generated changes along with the backend schema change. The source OpenAPI JSON used to generate the client is not committed; the script exports it from the running application and passes it to the generator.

## Tests and checks

Run from `frontend/`:

```bash
bun run lint
bun run test
```

Playwright tests are under `tests/`. They exercise the dashboard in a browser and require the application/backend and its data to be initialized. Run the full local stack with `bun run dev` from the root before running the tests. To open Playwright's interactive UI:

```bash
bun run test:ui
```

## Frontend layout

| Path | Responsibility |
| --- | --- |
| `src/main.tsx` | React application entry point. |
| `src/pages/` | Dashboard page and screen-level compositions. |
| `src/routes/` | Route-related application structure. |
| `src/components/` | Shared application components and reusable UI primitives. |
| `src/hooks/` | Query and application hooks. |
| `src/api/` | API-specific adapters/helpers. |
| `src/client/` | Generated OpenAPI client and types. |
| `src/schemas/` | Frontend data schemas/types. |
| `src/lib/`, `src/utils.ts` | Shared helpers. |
| `public/` | Static public assets. |
| `tests/` | Playwright end-to-end tests. |
