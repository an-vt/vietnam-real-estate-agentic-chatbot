"""Graph nodes. Each node returns updates to the shared state."""

import logging

from ..config import settings
from ..tools.sql import run_sql_question
from ..tools.vector import search_listings
from .chains import get_document_grader, get_llm, get_rewriter, get_router
from .state import GraphState

logger = logging.getLogger(__name__)


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
    result = get_router().invoke({"question": state["question"]})
    logger.info("Router -> %s", result.datasource)
    return {
        "datasource": result.datasource,
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
            {"document": document.page_content, "question": state["original_question"]}
        )
        == "yes"
    ]
    logger.info(
        "Listing grading: %d/%d relevant", len(relevant), len(state["documents"])
    )
    return {"documents": relevant}


def decide_after_grading(state: GraphState) -> str:
    if state["documents"] or state["retries"] >= settings.max_retries:
        return "done"
    return "rewrite"


def rewrite_query(state: GraphState) -> GraphState:
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
    logger.info("Rewrote listing query: %s", question)
    return {"question": question, "retries": state["retries"] + 1}


def route_after_rewrite(state: GraphState) -> str:
    """Retry the selected source; web search is an end route for now."""
    return "web_search" if state["datasource"] == "web_search" else "retrieve"


def query_sql(state: GraphState) -> GraphState:
    """Collect SQL evidence for the selected listings question."""
    document = run_sql_question(state["question"], get_llm())
    return {"documents": [document]}
