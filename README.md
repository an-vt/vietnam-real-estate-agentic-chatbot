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
The file sets the frontend and backend host ports and the frontend's API proxy
target. Both containers receive the same local environment file.

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
