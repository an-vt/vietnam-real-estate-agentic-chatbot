"""Assemble the routing graph and its listing retrieval loop."""

from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import GraphState


def build_graph():
    workflow = StateGraph(GraphState)
    workflow.add_node("route", nodes.route)
    workflow.add_node("retrieve", nodes.retrieve)
    workflow.add_node("grade_documents", nodes.grade_documents)
    workflow.add_node("rewrite_query", nodes.rewrite_query)
    workflow.add_node("query_sql", nodes.query_sql)

    workflow.add_edge(START, "route")
    workflow.add_conditional_edges(
        "route",
        nodes.select_datasource,
        {"vectorstore": "retrieve", "web_search": END, "sql": "query_sql"},
    )
    workflow.add_edge("retrieve", "grade_documents")
    workflow.add_conditional_edges(
        "grade_documents",
        nodes.decide_after_grading,
        {"done": END, "rewrite": "rewrite_query"},
    )
    workflow.add_conditional_edges(
        "rewrite_query",
        nodes.route_after_rewrite,
        {"retrieve": "retrieve", "web_search": END},
    )
    workflow.add_edge("query_sql", END)
    return workflow.compile()
