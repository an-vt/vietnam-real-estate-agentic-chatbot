import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
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


def _event(name: str, data: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def route_events(question: str) -> AsyncIterator[str]:
    """Translate LangGraph node updates into server-sent events."""
    yield _event("step", {"node": "route", "status": "running"})
    datasource = None
    result = None
    sources: list[dict[str, str]] = []
    retries = 0
    try:
        async with aclosing(get_graph().astream(
            {"question": question}, stream_mode="updates"
        )) as updates:
            async for update in updates:
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
                        elif datasource == "vectorstore":
                            yield _event("step", {"node": "retrieve", "status": "running"})
                        else:
                            yield _event("step", {"node": "web_search", "status": "running"})
                    elif node == "query_sql":
                        yield _event("step", {"node": "query_sql", "status": "completed"})
                        yield _event("step", {"node": "generate", "status": "running"})
                    elif node == "retrieve":
                        yield _event("step", {"node": "retrieve", "status": "completed"})
                        yield _event("step", {"node": "grade_documents", "status": "running"})
                    elif node == "grade_documents":
                        graded_documents = values["documents"]
                        yield _event("step", {"node": "grade_documents", "status": "completed"})
                        if graded_documents:
                            yield _event("step", {"node": "generate", "status": "running"})
                        elif retries < settings.max_retries:
                            yield _event("step", {"node": "rewrite_query", "status": "running"})
                        else:
                            yield _event("step", {"node": "web_search", "status": "running"})
                    elif node == "rewrite_query":
                        retries = values["retries"]
                        yield _event("step", {"node": "rewrite_query", "status": "completed"})
                        if datasource == "vectorstore":
                            yield _event("step", {"node": "retrieve", "status": "running"})
                        else:
                            yield _event("step", {"node": "web_search", "status": "running"})
                    elif node == "web_search":
                        datasource = values.get("datasource", "web_search")
                        yield _event("step", {"node": "web_search", "status": "completed"})
                        yield _event("step", {"node": "generate", "status": "running"})
                    elif node == "generate":
                        result = values["generation"]
                        sources = values.get("sources", [])
                        yield _event("step", {"node": "generate", "status": "completed"})
        if datasource is None or result is None:
            raise RuntimeError("The graph did not return a generated answer")
        yield _event("done", {
            "datasource": datasource, "result": result, "sources": sources,
        })
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
