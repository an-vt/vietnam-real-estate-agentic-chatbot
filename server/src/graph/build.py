"""Assemble the route-only agent graph."""

from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import GraphState


def build_graph():
    workflow = StateGraph(GraphState)
    workflow.add_node("route", nodes.route)
    workflow.add_edge(START, "route")
    workflow.add_edge("route", END)
    return workflow.compile()
