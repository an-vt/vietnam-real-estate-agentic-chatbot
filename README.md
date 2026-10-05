# Vietnam Real Estate Agentic Chatbot

This repository starts with a minimal Python API in `server/`. The `frontend/`
directory is reserved for a future user interface. There is no chatbot or RAG
implementation yet.

## Run the API

Use Python 3.10 or newer. On macOS with Python 3.11 installed:

```bash
cd server
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
fastapi dev src/main.py
```

Open <http://127.0.0.1:8000/> to see `{"message":"Hello World"}`. FastAPI's
interactive API documentation is at <http://127.0.0.1:8000/docs>.
