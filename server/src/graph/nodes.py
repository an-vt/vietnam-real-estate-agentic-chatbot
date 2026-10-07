"""Graph nodes. Each node returns updates to the shared state."""

import logging
import re
import time
from datetime import datetime

from langchain_core.documents import Document

from ..config import settings
from ..tools.sql import run_sql_question
from ..tools.vector import search_listings
from ..tools.web_search import (
    VIETNAM_TIME, explicit_location, explicit_price_range, search_web, verify_listings,
)
from .chains import (
    get_document_grader, get_generator, get_grounding_grader, get_llm,
    get_rewriter, get_router, get_web_listing_extractor, get_web_request,
)
from .state import GraphState

logger = logging.getLogger(__name__)
SOURCE_NOTES = {
    "vectorstore": "the local listing database",
    "web_search": "a public web search",
    "sql": "a SQL query over the local listing database",
}


def _format_docs(documents: list[Document]) -> str:
    return "\n\n".join(
        f"[{document.metadata.get('source', 'unknown')}]\n{document.page_content}"
        for document in documents
    )


# --------------------------------------------------------------------------
# Routing decisions (pure functions over the state)
# --------------------------------------------------------------------------
def select_datasource(state: GraphState) -> str:
    logger.info(
        "Selecting data source for question: %s is source: %s",
        state["question"],
        state["datasource"],
    )
    return state["datasource"]


def route(state: GraphState) -> GraphState:
    """Choose the source for the original question."""
    started = time.monotonic()
    logger.info("Routing started")
    datasource = get_router().invoke({"question": state["question"]}).datasource
    logger.info("Routing finished in %.1fs", time.monotonic() - started)
    logger.info("Router -> %s", datasource)
    return {
        "datasource": datasource,
        "original_question": state["question"],
        "retries": 0,
    }


def retrieve(state: GraphState) -> GraphState:
    documents = search_listings(state["question"], settings.retrieval_k)

    logger.info("Retrieved %d listings", len(documents))
    return {"documents": documents}


def grade_documents(state: GraphState) -> GraphState:
    if not state["documents"]:
        return {"documents": []}
    grader = get_document_grader()
    relevant = [
        document
        for document in state["documents"]
        if grader.invoke(
            {"document": document.page_content, "question": state["question"]}
        )
        == "yes"
    ]
    logger.info(
        "Listing grading: %d/%d relevant", len(relevant), len(state["documents"])
    )
    return {"documents": relevant}


def decide_after_grading(state: GraphState) -> str:
    if state["documents"]:
        return "generate"
    if state["retries"] >= settings.max_retries:
        logger.info(
            "No relevant documents after %d retries, falling back to web",
            settings.max_retries,
        )
        return "web_search"
    return "rewrite"


def rewrite_query(state: GraphState) -> GraphState:
    started = time.monotonic()
    logger.info("Query rewrite started (attempt %d)", state["retries"] + 1)
    question = (
        get_rewriter()
        .invoke(
            {
                "original_question": state["original_question"],
                "question": state["question"],
            }
        )
        .strip()
    )
    if not question:
        raise ValueError("The query rewriter returned an empty search query")
    logger.info(
        "Query rewrite finished in %.1fs: %s", time.monotonic() - started, question,
    )
    return {"question": question, "retries": state["retries"] + 1}


def route_after_rewrite(state: GraphState) -> str:
    """Retry the selected source with the new query."""
    return "web_search" if state["datasource"] == "web_search" else "retrieve"


async def web_search(state: GraphState) -> GraphState:
    """Search public pages, keeping only verified matches for listing requests."""
    request = state.get("web_request")
    if request is None:
        started = time.monotonic()
        logger.info("Web request parsing started")
        request = await get_web_request().ainvoke({
            "question": state["original_question"],
            "today": datetime.now(VIETNAM_TIME).date().isoformat(),
        })
        logger.info("Web request parsing finished in %.1fs", time.monotonic() - started)
        if not request.search_query.strip():
            request.search_query = state["original_question"]
        explicit_price = explicit_price_range(state["original_question"])
        if explicit_price is not None:
            request.price_million = explicit_price
        location = explicit_location(state["original_question"])
        if location:
            request.location = location
        if re.search(r"\b(?:mới nhất|moi nhat|latest|newest)\b", state["original_question"], re.IGNORECASE):
            request.sort_newest = True
    query = request.search_query if state["retries"] == 0 else state["question"]
    started = time.monotonic()
    logger.info("DDGS search started (attempt %d)", state["retries"] + 1)
    pages = await search_web(
        query, request.location if request.kind == "listings" else None,
    )
    logger.info("DDGS search finished in %.1fs", time.monotonic() - started)
    documents = pages
    if request.kind == "listings":
        read_pages = [page for page in pages if page.metadata.get("page_read")]
        documents = []
        if read_pages:
            context = "\n\n".join(
                f"[{index}] Title: {page.metadata['title']}\n"
                f"URL: {page.metadata['source']}\n{page.page_content}"
                for index, page in enumerate(read_pages, 1)
            )
            started = time.monotonic()
            logger.info("Listing extraction started for %d pages", len(read_pages))
            batch = await get_web_listing_extractor().ainvoke({
                "question": state["original_question"], "pages": context,
            })
            logger.info("Listing extraction finished in %.1fs", time.monotonic() - started)
            documents = verify_listings(read_pages, batch, request)
    logger.info("Web search returned %d usable sources", len(documents))
    return {
        "question": query,
        "datasource": "web_search",
        "web_request": request,
        "documents": documents,
    }


async def generate(state: GraphState) -> GraphState:
    """Answer strictly from the gathered evidence."""
    documents = state["documents"]
    started = time.monotonic()
    logger.info("Answer generation started")
    answer = (await get_generator().ainvoke({
        "context": _format_docs(documents),
        "question": state.get("original_question", state["question"]),
        "source_note": SOURCE_NOTES.get(state["datasource"], "an unknown source"),
    })).strip()
    logger.info("Answer generation finished in %.1fs", time.monotonic() - started)
    sources = [
        {"title": str(document.metadata.get("title", document.metadata.get("source", "unknown"))),
         "url": str(document.metadata["source"])}
        for document in documents
        if document.metadata.get("source")
    ]
    return {"generation": answer, "sources": sources}


def grade_generation(state: GraphState) -> str:
    """Retry when a generated answer is not grounded in its evidence."""
    if state["datasource"] == "sql" or not state["documents"]:
        return "useful"
    grounded = get_grounding_grader().invoke({
        "documents": _format_docs(state["documents"]),
        "generation": state["generation"],
    })
    if grounded == "yes":
        return "useful"
    if state["retries"] < settings.max_retries:
        logger.info("Answer not grounded, rewriting query and retrying")
        return "rewrite"
    logger.info("Answer not grounded but retry budget exhausted, returning anyway")
    return "useful"


def query_sql(state: GraphState) -> GraphState:
    """Collect SQL evidence for the selected listings question."""
    document = run_sql_question(state["question"], get_llm())
    return {"documents": [document]}
