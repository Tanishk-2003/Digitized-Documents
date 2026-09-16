# Pharma Stock & Sale Intelligence — Review UI

React (Vite) frontend for the pipeline in the repo root (`src/pharma_di/`). Lets a
human reviewer see what the pipeline extracted from a distributor statement side by
side with the source photo, approve or correct flagged rows, and export results.

## Running everything locally

There is no separate queue/worker process to start — background pipeline jobs run
in-process inside the API server (a thread pool; see `src/pharma_di/workers/jobs.py`),
not via Redis/RQ. Two processes are all you need, each in its own terminal from the
**repo root** (not this `ui/` folder) for the first one:

**1. API server** (repo root, with the project's virtualenv active). This project
isn't `pip install`-ed into the venv, so `src/` needs to be on `PYTHONPATH` —
the same reason `alembic` and `scripts/run_pipeline.py` need it:

```bash
# bash / Git Bash
PYTHONPATH=src uvicorn pharma_di.api.app:app --reload --port 8000
```

```powershell
# PowerShell
$env:PYTHONPATH = "src"; uvicorn pharma_di.api.app:app --reload --port 8000
```

Confirm it's up at [http://localhost:8000/health](http://localhost:8000/health) or
the interactive docs at [http://localhost:8000/docs](http://localhost:8000/docs).

**If you use `uv run` instead of activating the venv directly**: pass `--active`
(`uv run --active uvicorn ...`). Without it, `uv run` ignores whichever venv is
currently active and manages its own separate `.venv`, freshly installing
packages into it — on a machine with an Application Control / endpoint-security
policy, that fresh install of `orjson` (a FastAPI dependency, a compiled native
extension) can get blocked outright (`DLL load failed ... Application Control
policy has blocked this file`), even though the exact same package works fine
in an already-set-up venv. This isn't a bug in this project; it's the
difference between running against a venv that's already there versus one
`uv` just built.

**2. This UI** (from `ui/`):

```bash
npm install   # first time only
npm run dev
```

Vite prints a local URL (typically `http://localhost:5173`) — open it in a browser.
The UI talks to the API at `http://localhost:8000` by default; override with a
`VITE_API_URL` environment variable (or a `ui/.env.local` file) if the API runs
somewhere else.

## What's here

| Tab | Page | Purpose |
|---|---|---|
| Review Queue | `ReviewQueuePage` | Documents with rows currently flagged `needs_review`, with a summary of why. |
| Documents | `DocumentsPage` | Every persisted document, with row counts and a per-document Excel export. |
| Final Output | `FinalOutputPage` | The uniform 12-column Stock & Sale table across every document, regardless of the source layout — sortable, filterable, with a one-click export of everything shown. |
| Jobs | `JobsPage` | Background processing jobs (queued/processing/completed/failed), auto-refreshing every 5s while any are in flight. |
| Upload | `UploadPage` | Drag-and-drop or click-to-browse document ingestion. |

Opening a flagged document from the Review Queue or Documents tab goes to
`DocumentReviewPage`: the source image next to extracted rows, a per-field
confidence bar for each numeric value, and Approve / Correct actions. A correction
is sent to the API's `/api/review/{id}/correct` route, which can also promote a
previously-unrecognized column header into the pipeline's mapping dictionary
(`config/column_mappings.yaml`) so the same header resolves automatically on the
next document that uses it.

## Build

```bash
npm run build
```

Output lands in `dist/`. It's a static SPA — serve it with any static file host,
pointed at the running API via `VITE_API_URL` set at build time.
