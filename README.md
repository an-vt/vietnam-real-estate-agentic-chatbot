# Vietnam Real Estate Agentic Chatbot

This repository has a React chat frontend and a small FastAPI backend. The backend
logs received messages and returns a fixed acknowledgment. It does not implement
chatbot or RAG logic yet.

## Run everything locally with Docker

From `infra/local/`:

```bash
cd infra/local
make up
```

Open <http://localhost:5173/> for the frontend or <http://localhost:8000/docs>
for the API documentation. `make up` builds and starts both containers in the
background. Use `make logs` to see chat messages logged by the backend, and
`make down` to stop the containers.

The working tree includes `infra/local/.env` with nonsecret local defaults. It is
gitignored. After a fresh clone, create it before running any Make command:

```bash
cd infra/local
cp .env.example .env
make up
```

Every Make command requires `.env` and prints `Missing file .env` if it is absent.
The file sets the frontend and backend host ports, the frontend's API proxy
target, and PostgreSQL connection settings. The PostgreSQL host port defaults
to 5433, and its data persists in a named Docker volume.

## Import real estate listings

The importer runs on the host. Start PostgreSQL, then install the optional
Python dependencies and load the CSV once:

```bash
cd infra/local
docker compose --env-file .env -f docker-compose.yml up -d postgres
cd ../../server
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[ingest]'
.venv/bin/python -m src.script.ingest_csv \
  --csv /Users/an/Downloads/VN-real-estate-Apr-Sept-2025.csv
```

The command uses the database settings in `infra/local/.env` and accepts
`--batch-size` (default 32) and `--force`. BGE-M3 is downloaded on the first
run. Each batch commits separately. Rerunning the same command resumes by
skipping listings with an equal or newer stored scrape time; `--force`
re-embeds every listing. The table is
`vietnamese_real_estate.documents`; `price` is in millions of VND, and each
document has a 1,024-dimensional embedding. Alembic migration `20261005_01`
creates the extension and table before import; migration `20261005_02` creates
the HNSW cosine index after the import. The importer applies both migrations
at the appropriate points. To inspect migration state, run
`cd server && .venv/bin/alembic current`. The CSV remains on the host and is
not needed when Compose starts again.

## Run without Docker

Use Python 3.10 or newer. On macOS with Python 3.11 installed:

```bash
cd server
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
fastapi dev src/main.py
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` to <http://127.0.0.1:8000> outside Docker. The API also
accepts `POST /api/chat` with `{"message":"Hello"}` and returns
`{"reply":"Message received"}`.
