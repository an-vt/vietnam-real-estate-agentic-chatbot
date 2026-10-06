"""Graph nodes. Each node returns updates to the shared state."""

import logging

from .chains import get_router
from .state import GraphState


logger = logging.getLogger(__name__)


def route(state: GraphState) -> GraphState:
    """Choose a data source and stop; source handlers come in later steps."""
    result = get_router().invoke({"question": state["question"]})
    logger.info("Router -> %s", result.datasource)
    return {
        "datasource": result.datasource,
        "original_question": state["question"],
        "retries": 0,
    }
