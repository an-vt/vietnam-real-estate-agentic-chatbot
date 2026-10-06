"""Lazy LLM chains used by graph nodes."""

from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from ..config import settings
from .state import Datasource


class RouteQuery(BaseModel):
    """Select the single source best suited to a question."""

    datasource: Datasource = Field(description="The best source for this question")


ROUTER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Route the user's question to exactly one data source:\n"
            '- "vectorstore": {kb_description}\n'
            '- "sql": {sql_description}\n'
            '- "web_search": current events, recent facts or information outside '
            "the listing database.\n"
            "Choose the best source. Both vectorstore and sql refer to the same "
            "PostgreSQL listings table; they differ in how it will be searched.",
        ),
        ("human", "{question}"),
    ]
).partial(
    kb_description=settings.kb_description,
    sql_description=settings.sql_description,
)


@lru_cache(maxsize=1)
def get_llm() -> ChatOllama:
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        temperature=settings.llm_temperature,
    )


@lru_cache(maxsize=1)
def get_router():
    return ROUTER_PROMPT | get_llm().with_structured_output(
        RouteQuery, method="json_schema"
    )
