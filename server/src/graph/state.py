"""Shared state for the agent graph."""

from typing import Literal, TypedDict

from langchain_core.documents import Document


Datasource = Literal["vectorstore", "web_search", "sql"]


class GraphState(TypedDict, total=False):
    question: str
    original_question: str
    datasource: Datasource
    documents: list[Document]
    retries: int
