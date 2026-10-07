"""Search public pages and verify web listing evidence."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain_core.documents import Document

from ..graph.state import NumericRange, WebListingBatch, WebRequest

logger = logging.getLogger(__name__)
VIETNAM_TIME = timezone(timedelta(hours=7))
NUMBER = r"\d+(?:[.,]\d+)*"
PRICE_UNIT = r"(?:tỷ|tỉ|ty|triệu|trieu|million|billion)"
WEB_SEARCH_TIMEOUT_SECONDS = 60


def _fold(value: str) -> str:
    plain = "".join(
        character for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    ).replace("đ", "d")
    # Vietnamese place names may use either i or y (for example, Mĩ/Mỹ).
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("y", "i")).strip()


def _public_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def _search_web(query: str, location: str | None = None) -> list[Document]:
    """Search five results and read up to two likely pages."""
    started = time.monotonic()
    with DDGS(timeout=5) as client:
        try:
            results = client.text(query, max_results=5)
        except DDGSException as error:
            logger.warning(
                "DDGS returned no results after %.1fs: %s",
                time.monotonic() - started,
                error,
            )
            return []
        logger.info("DDGS returned %d results in %.1fs", len(results), time.monotonic() - started)
        seen: set[str] = set()
        candidates = []
        for result in results:
            url = str(result.get("href") or "")
            if url in seen or not _public_url(url):
                continue
            seen.add(url)
            candidates.append(result)

        if location:
            words = set(_fold(location).split())
            candidates.sort(
                key=lambda item: sum(
                    word in set(_fold(f'{item.get("title", "")} {item.get("body", "")}').split())
                    for word in words
                ),
                reverse=True,
            )

        documents = []
        for index, item in enumerate(candidates):
            url = str(item["href"])
            snippet = str(item.get("body") or "").strip()
            content = snippet
            page_read = False
            if index < 2:
                started = time.monotonic()
                logger.info("Page read started: %s", url)
                try:
                    extracted = client.extract(url, fmt="text_plain")
                    page_text = str(extracted.get("content") or "").strip()
                    if page_text:
                        content = page_text[:2000]
                        page_read = True
                except Exception as error:
                    logger.warning("Could not read web page %s: %s", url, error)
                logger.info(
                    "Page read finished in %.1fs (success=%s): %s",
                    time.monotonic() - started,
                    page_read,
                    url,
                )
            if content:
                documents.append(Document(
                    page_content=content,
                    metadata={
                        "source": url,
                        "title": str(item.get("title") or url),
                        "snippet": snippet,
                        "page_read": page_read,
                    },
                ))
        return documents


async def search_web(query: str, location: str | None = None) -> list[Document]:
    """Search public pages within the web-search deadline."""
    started = time.monotonic()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_search_web, query, location),
            timeout=WEB_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Web search timed out after %.1fs: %s",
            time.monotonic() - started,
            query,
        )
        return []


def _number(value: str) -> Decimal | None:
    value = value.strip()
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif value.count(".") > 1 or (
        value.count(".") == 1 and len(value.split(".")[1]) == 3
    ):
        value = value.replace(".", "")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _price_amount(value: str, unit: str) -> float | None:
    number = _number(value)
    if number is None:
        return None
    unit = _fold(unit)
    if unit in {"ti", "billion"}:
        number *= 1000
    elif unit not in {"trieu", "million"}:
        return None
    return float(number)


def parse_price_million(text: str) -> float | None:
    """Parse one asking price, not a category price range."""
    lower = text.lower()
    if re.search(rf"{NUMBER}\s*(?:-|–|—|đến|den|to)\s*{NUMBER}", lower):
        return None
    parts = re.findall(rf"({NUMBER})\s*({PRICE_UNIT})\b", lower)
    if not parts or len(parts) > 2:
        return None
    units = [_fold(unit) for _, unit in parts]
    if len(parts) == 2 and not (
        units[0] in {"ti", "billion"} and units[1] in {"trieu", "million"}
    ):
        return None
    amounts = [_price_amount(value, unit) for value, unit in parts]
    return sum(amounts) if all(amount is not None for amount in amounts) else None


def within_range(value: float, requested: NumericRange | None) -> bool:
    if requested is None:
        return True
    if requested.min_value is not None:
        if value < requested.min_value or (
            value == requested.min_value and not requested.min_inclusive
        ):
            return False
    if requested.max_value is not None:
        if value > requested.max_value or (
            value == requested.max_value and not requested.max_inclusive
        ):
            return False
    return True


def explicit_price_range(question: str) -> NumericRange | None:
    """Independently preserve common explicit price limits from user wording."""
    text = question.lower()
    between = re.search(
        rf"(?:từ|tu|between)\s*({NUMBER})\s*(?:{PRICE_UNIT})?\s*"
        rf"(?:đến|den|to|[-–])\s*({NUMBER})\s*({PRICE_UNIT})\b",
        text,
    )
    if between:
        low = _price_amount(between[1], between[3])
        high = _price_amount(between[2], between[3])
        if low is not None and high is not None:
            return NumericRange(min_value=low, max_value=high)
    bounds = {}
    for expression, field, inclusive in (
        (r"(?:dưới|duoi|under|less than|<)", "max_value", False),
        (r"(?:không quá|khong qua|at most|<=)", "max_value", True),
        (r"(?:trên|tren|over|more than|>)", "min_value", False),
        (r"(?:ít nhất|it nhat|at least|>=)", "min_value", True),
    ):
        match = re.search(rf"{expression}\s*({NUMBER})\s*({PRICE_UNIT})\b", text)
        if match:
            amount = _price_amount(match[1], match[2])
            if amount is not None:
                bounds[field] = amount
                bounds[field.replace("value", "inclusive")] = inclusive
    return NumericRange(**bounds) if bounds else None


def explicit_location(question: str) -> str | None:
    """Keep a place stated after a location cue when the model omits it."""
    match = re.search(
        r"\b(?:khu vực|tại|ở)\s+(.+?)(?=\s+(?:dưới|trên|từ|không quá|ít nhất|mới nhất)\b|$)",
        question,
        re.IGNORECASE,
    )
    return match[1].strip(" ,.") if match else None


def _evidence_in_page(evidence: str, page: str) -> bool:
    return bool(evidence.strip()) and " ".join(evidence.split()).casefold() in " ".join(page.split()).casefold()


def _simple_number(text: str) -> float | None:
    match = re.search(NUMBER, text)
    value = _number(match[0]) if match else None
    return float(value) if value is not None else None


def _posted_date(text: str, today: date) -> date | None:
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if match:
        try:
            return date(int(match[3]), int(match[2]), int(match[1]))
        except ValueError:
            return None
    lower = text.casefold()
    if "hôm nay" in lower or "today" in lower:
        return today
    if "hôm qua" in lower or "yesterday" in lower:
        return today - timedelta(days=1)
    match = re.search(r"(\d+)\s*(?:ngày trước|days? ago)", lower)
    if match:
        return today - timedelta(days=int(match[1]))
    return None


def verify_listings(
    pages: list[Document], batch: WebListingBatch, request: WebRequest,
    today: date | None = None,
) -> list[Document]:
    """Turn sourced candidate fields into strictly filtered listing documents."""
    today = today or datetime.now(VIETNAM_TIME).date()
    verified = []
    seen: set[str] = set()
    for item in batch.listings:
        if not item.is_detail_page or not 1 <= item.source_index <= len(pages):
            continue
        page = pages[item.source_index - 1]
        if not page.metadata.get("page_read"):
            continue
        if re.search(r"gia[-_/]tu[-_/].*[-_/]den[-_/]", urlparse(str(page.metadata["source"])).path):
            continue
        if _fold(item.title) not in _fold(str(page.metadata.get("title", ""))):
            continue
        if not all(_evidence_in_page(value, page.page_content) for value in (
            item.title, item.location_text, item.price_text, item.posted_text,
        )):
            continue
        if request.location:
            requested_words = set(_fold(request.location).split())
            location_words = set(_fold(item.location_text).split())
            if not requested_words.issubset(location_words):
                continue
        if request.property_type != "any" and item.property_type != request.property_type:
            continue
        price = parse_price_million(item.price_text)
        posted = _posted_date(item.posted_text, today)
        if price is None or posted is None or posted > today:
            continue
        if not within_range(price, request.price_million):
            continue
        area = None
        if request.area_m2 is not None:
            if not _evidence_in_page(item.area_text, page.page_content):
                continue
            area = _simple_number(item.area_text)
            if area is None or not within_range(area, request.area_m2):
                continue
        bedrooms = None
        if request.bedrooms is not None:
            if not _evidence_in_page(item.bedrooms_text, page.page_content):
                continue
            bedrooms = _simple_number(item.bedrooms_text)
            if bedrooms is None or not within_range(bedrooms, request.bedrooms):
                continue
        url = str(page.metadata["source"])
        if url in seen:
            continue
        seen.add(url)
        verified.append(Document(
            page_content=page.page_content,
            metadata={
                "source": url, "title": item.title,
                "location": item.location_text, "price_million": price,
                "posted_date": posted.isoformat(), "property_type": item.property_type,
                "area_m2": area, "bedrooms": bedrooms,
            },
        ))
    if request.sort_newest:
        verified.sort(key=lambda document: document.metadata["posted_date"], reverse=True)
    return verified[:3]
