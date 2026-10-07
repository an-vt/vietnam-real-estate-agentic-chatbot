# Vietnam Real Estate Agentic Chatbot

This repository has a React chat frontend and a FastAPI backend. LangGraph
routes each question to `sql`, `vectorstore`, or `web_search`. SQL questions
run a read-only PostgreSQL query. Vector questions search the same listings by
meaning and display relevant matches. Web questions search current public pages
and return an answer with source links.

## Run everything locally with Docker

From `infra/local/`:

```bash
cd infra/local
make up
```

Pull the router model into the Ollama container after the first start:

```bash
docker compose --env-file .env -f docker-compose.yml exec ollama ollama pull qwen2.5:7b
```

Open <http://localhost:5173/> for the frontend or <http://localhost:8000/docs>
for the API documentation. `make up` starts the frontend, backend, PostgreSQL,
and Ollama in the background. Use `make logs` to inspect service logs, and
`make down` to stop the containers. Ollama models persist in a named volume.

The working tree includes `infra/local/.env` with nonsecret local defaults. It is
gitignored. After a fresh clone, create it before running any Make command:

```bash
cd infra/local
cp .env.example .env
make up
```

Every Make command requires `.env` and prints `Missing file .env` if it is absent.
The file sets ports, the frontend API proxy target, Ollama model settings, and
PostgreSQL connection settings. The PostgreSQL host port defaults to 5433, and
its data persists in a named Docker volume. Compose publishes the Docker
Ollama service on host port 11435 for a backend started from VS Code. No
macOS Ollama installation is needed.
With the default local embedding provider, the backend downloads BGE-M3 on its
first vector search; Docker keeps it in a named cache volume for later runs.

To use OpenRouter instead, set `LLM_PROVIDER=openrouter`, set `LLM_MODEL` to an
OpenRouter model slug such as `qwen/qwen3.5-27b`, and provide `LLM_API_KEY`. The
Ollama service can remain running but is not used for
LLM calls.

## Query the listings

The router uses a structured output Ollama call. `sql` means exact listing
filters, counts, or calculations; `vectorstore` means meaning-based search of
the same listings; `web_search` means current or outside information, including
the latest public property ads. The SQL route queries
`vietnamese_real_estate.documents`; the vector route searches its existing
embeddings. The Ollama router makes every source decision. The web route searches
with DDGS and reads up to two result pages.

`POST /api/chat` accepts `{"message":"How many homes in Hà Nội cost under 3000 million VND?"}`
and returns a `text/event-stream` response. It emits `step` events for the
selected path. All `done` events contain `datasource` and `result`; web events
also contain `sources` with titles and URLs. Failures emit an `error`
event. Inspect the stream with:

```bash
curl -N -H 'Content-Type: application/json' \
  -d '{"message":"How many homes in Hà Nội cost under 3000 million VND?"}' \
  http://127.0.0.1:8000/api/chat
```

The SQL query is generated with Ollama and may be corrected up to three times.
The prompt asks for a single `SELECT` over the listings table. The SQL guard
accepts a statement beginning with `SELECT` or `WITH` and rejects extra
semicolons and common write or DDL keywords. PostgreSQL executes accepted
queries in a read-only transaction with a five-second timeout, and at most 20
rows are shown. The prompt includes the table DDL, one named example row
without its embedding values, and exact `province` and `property_type` values
read from PostgreSQL for the question. The compiled graph is reused across
requests.

Vector search embeds the question with the same configured model used for import,
then reads the four nearest listings with pgvector cosine distance. An Ollama
grader removes irrelevant results. If none remain, a query rewriter can retry
the search twice. Chat shows the graded listings with key fields and a short
description, or reports that no relevant listings were found. This branch
returns listings rather than an LLM-written answer.
Vector ranking does not apply price filters. The grader sees each listing's
price, but exact budget constraints should use the SQL route; vector results
may include listings outside a requested budget.

For a current public listing request, the web route extracts individual ads
from pages it could read, checks that key fields appear on the same page, and
filters explicit price, area, bedroom, location, and property type requirements.
It excludes category pages and listings without a verifiable asking price or
posting date. When no match is verified, it rewrites the query up to
`MAX_RETRIES` times and then says it could not verify a match. General web
questions use the retrieved text or search snippets to compose a cited answer.
Routing and all web retries share a 60-second deadline; an unfinished request
ends with a timeout error. Web model calls have bounded output, DDGS returns at
most five results, and each read page contributes at most 2,000 characters.
Application logs use UTC timestamps and include elapsed time for each web stage.
Live DDGS tests need internet access and may fail when the service is unavailable.

### SQL accuracy roadmap

The current SQL path uses a fixed DDL description and example row, plus live
categorical values. A future enhancement will follow the pattern in
[AWS's conversational data assistant](https://aws.amazon.com/blogs/machine-learning/build-a-conversational-data-assistant-part-1-text-to-sql-with-amazon-bedrock-agents/):

1. Refresh a small metadata catalog from PostgreSQL, including table columns,
   categorical values, and curated question-to-SQL examples.
2. Retrieve the metadata relevant to each question before SQL generation.
3. Validate candidate queries with PostgreSQL `EXPLAIN`, return validation
   errors to the SQL model for correction, and measure accuracy against a
   set of verified listing questions.

This is a planned PostgreSQL implementation of the pattern; it does not need
AWS Glue, DynamoDB, or Redshift.

## Configuration

`server/src/config.py` is the only Python module that reads environment
variables. It loads `infra/local/.env` when available and keeps exported or
Compose-provided values ahead of values in the file. The importer and Alembic
also consume its `settings` object. Compose connects the backend to the Ollama
container at `http://ollama:11434`. A backend run on the host uses
`OLLAMA_BASE_URL` to reach the same container through its published port.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_LOG_LEVEL` | `INFO` | Application logs in the backend container (`DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`); Uvicorn access logs are separate |
| `LLM_PROVIDER` | `local` | `local` for Ollama, `openai` for OpenAI, or `openrouter` for OpenRouter |
| `LLM_MODEL` | `qwen2.5:7b` | Provider model used for routing, grading, rewriting, and SQL generation |
| `LLM_API_KEY` | Unset | Required when `LLM_PROVIDER` is `openai` or `openrouter`; used by both chat and embeddings |
| `OLLAMA_BASE_URL` | `http://localhost:11435` | Docker Ollama address for host runs |
| `LLM_TEMPERATURE` | `0` | Routing and SQL model temperature |
| `RETRIEVAL_K` | `4` | Maximum nearest listings read on each vector search |
| `MAX_RETRIES` | `2` | Maximum query rewrites after grading finds no relevant listing |
| `LLM_EMBEDDING_MODEL` | `BAAI/bge-m3` for `local`, `text-embedding-3-small` otherwise | Model used by both import and retrieval |
| `KB_DESCRIPTION`, `SQL_DESCRIPTION` | Built-in listing descriptions | Source descriptions in the router prompt |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Local PostgreSQL defaults | Importer, Alembic, and SQL query connection; Compose overrides host and port for the backend |

Run the backend tests and frontend build in the containers with `cd infra/local && make test`.

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
`--batch-size` (default 32) and `--force`. Local BGE-M3 is downloaded on the first
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

Embeddings use the same `LLM_PROVIDER` as chat. To use OpenAI embeddings in
production, set `LLM_PROVIDER=openai` and `LLM_API_KEY` (in `infra/local/.env`
for the local Compose setup). To use OpenRouter's OpenAI-compatible embeddings,
set `LLM_PROVIDER=openrouter` and `LLM_API_KEY`. The default
`text-embedding-3-small` request uses 1,024 dimensions, matching the pgvector
column. Import the CSV into a fresh database with the selected provider, or
run the importer with `--force` if the database already has embeddings from
another model. Ingestion and retrieval must use the same provider and model;
vectors from different models cannot be mixed in one search index.

## Debug the Docker backend in VS Code

From `infra/local/`, start the full stack:

```bash
make up
make logs
```

In VS Code, select **FastAPI: attach to Docker** and press F5. Set a breakpoint
at `server/src/graph/nodes.py:15`, then send a question through the frontend at
<http://localhost:5173/>. The backend runs in Docker and VS Code attaches to it
on localhost port 5678. Attach before sending the question. The debug backend
does not use Uvicorn reload; rerun `make up` after changing backend code.

`APP_LOG_LEVEL=INFO` (the default) prints router decisions such as
`Router -> sql` in `make logs`. Set `APP_LOG_LEVEL=WARNING` in
`infra/local/.env` to hide INFO messages, then rerun `make up` to recreate
the backend with the new environment.

## Debug the route on the host in VS Code

The repository includes `.vscode/launch.json` for the **FastAPI: route** debug
configuration. It runs the server from `server/` using `server/.venv` and does
not enable Uvicorn reload, so breakpoints remain in the request process.

From the repository root:

1. Start Ollama and PostgreSQL: `docker compose --env-file infra/local/.env -f infra/local/docker-compose.yml up -d ollama postgres`. For an existing `.env`, add `OLLAMA_PORT=11435` and `OLLAMA_BASE_URL=http://localhost:11435`.
2. Pull the model with `docker compose --env-file infra/local/.env -f infra/local/docker-compose.yml exec ollama ollama pull qwen2.5:7b`.
3. Install the backend into `server/.venv` with `server/.venv/bin/python -m pip install -e ./server`.
4. If a Compose backend is already running on port 8000, stop only that service with `docker compose --env-file infra/local/.env -f infra/local/docker-compose.yml stop backend`.
5. In VS Code, select **FastAPI: route**, press F5, and set breakpoints in `server/src/graph/nodes.py` (`route`), `chains.py` (`get_router`), or `server/src/main.py` (`route_events`). Send a question from the frontend or the `curl -N` command above.

To use the React frontend while debugging the host backend, run `cd frontend && npm ci && npm run dev`. Vite proxies `/api` to <http://127.0.0.1:8000> outside Docker.

## Run the app on the host with Docker Ollama

Use Python 3.10 or newer. On macOS with Python 3.11 installed:

```bash
cd server
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
uvicorn src.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Start the Docker Ollama and PostgreSQL services and pull the model as shown
above before sending SQL questions. The host backend uses the `OLLAMA_BASE_URL`
in `infra/local/.env`, or `http://localhost:11435` if it is unset.
