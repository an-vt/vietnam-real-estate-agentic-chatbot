import json
import logging
from collections.abc import Iterator
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import settings
from .graph.build import build_graph
from .logger import setup_logging

setup_logging(settings.app_log_level)

logger = logging.getLogger(__name__)

app = FastAPI()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


@lru_cache(maxsize=1)
def get_graph():
    """Compile once, like the cached graph in the reference app."""
    return build_graph()


def _event(name: str, data: dict[str, str]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def route_events(question: str) -> Iterator[str]:
    """Translate LangGraph node updates into server-sent events."""
    yield _event("step", {"node": "route", "status": "running"})
    datasource = None
    result = None
    try:
        for update in get_graph().stream({"question": question}, stream_mode="updates"):
            for node, values in update.items():
                if not values:
                    continue
                if node == "route":
                    datasource = values["datasource"]
                    yield _event(
                        "step",
                        {"node": "route", "status": "completed", "datasource": datasource},
                    )
                    if datasource == "sql":
                        yield _event("step", {"node": "query_sql", "status": "running"})
                elif node == "query_sql":
                    result = values["documents"][0].page_content
                    yield _event("step", {"node": "query_sql", "status": "completed"})
        if datasource is None:
            raise RuntimeError("The graph did not return a data source")
        if datasource == "sql":
            if result is None:
                raise RuntimeError("The SQL node did not return a result")
            yield _event("done", {"datasource": datasource, "result": result})
        else:
            yield _event("done", {"datasource": datasource})
    except Exception:
        logger.exception("Chat request failed")
        yield _event(
            "error",
            {"message": "Could not complete the request. Please try again."},
        )


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.post("/api/chat")
def chat(payload: ChatRequest) -> StreamingResponse:
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="message must not be blank")
    return StreamingResponse(
        route_events(question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
