"""Assemble the routing graph with its SQL branch."""

from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import GraphState


def build_graph():
    workflow = StateGraph(GraphState)
    workflow.add_node("route", nodes.route)
    workflow.add_node("query_sql", nodes.query_sql)

    workflow.add_edge(START, "route")
    workflow.add_conditional_edges(
        "route",
        nodes.select_datasource,
        {"vectorstore": END, "web_search": END, "sql": "query_sql"},
    )
    workflow.add_edge("query_sql", END)
    return workflow.compile()
