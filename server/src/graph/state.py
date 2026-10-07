"""Shared state for the agent graph."""

from typing import Literal, TypedDict

from langchain_core.documents import Document
from pydantic import BaseModel


Datasource = Literal["vectorstore", "web_search", "sql"]


class NumericRange(BaseModel):
    min_value: float | None = None
    max_value: float | None = None
    min_inclusive: bool = True
    max_inclusive: bool = True


class WebRequest(BaseModel):
    search_query: str
    kind: Literal["general", "listings"]
    location: str | None = None
    property_type: Literal["house", "apartment", "any"] = "any"
    price_million: NumericRange | None = None
    area_m2: NumericRange | None = None
    bedrooms: NumericRange | None = None
    sort_newest: bool = False
    answer_language: Literal["vi", "en"] = "vi"


class WebListingCandidate(BaseModel):
    source_index: int
    is_detail_page: bool
    title: str
    property_type: Literal["house", "apartment", "other"]
    location_text: str
    price_text: str
    posted_text: str
    area_text: str = ""
    bedrooms_text: str = ""


class WebListingBatch(BaseModel):
    listings: list[WebListingCandidate]


class GraphState(TypedDict, total=False):
    question: str
    original_question: str
    datasource: Datasource
    documents: list[Document]
    retries: int
    web_request: WebRequest
    generation: str
    sources: list[dict[str, str]]
