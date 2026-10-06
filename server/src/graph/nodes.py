"""Graph nodes. Each node returns updates to the shared state."""

import logging

from ..tools.sql import run_sql_question
from .chains import get_llm, get_router
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
    """Choose a data source and stop; source handlers come in later steps."""
    result = get_router().invoke({"question": state["question"]})
    logger.info("Router -> %s", result.datasource)
    return {
        "datasource": result.datasource,
        "original_question": state["question"],
        "retries": 0,
    }


def query_sql(state: GraphState) -> GraphState:
    """Collect SQL evidence for the selected listings question."""
    document = run_sql_question(state["question"], get_llm())
    return {"documents": [document]}
