"""Web search integration and listing evidence checks."""

import asyncio
import time
import unittest
from datetime import date
from unittest.mock import patch

from langchain_core.documents import Document

from src.graph.state import WebListingBatch, WebListingCandidate, WebRequest
from src.tools.web_search import explicit_location, explicit_price_range, search_web, verify_listings


TODAY = date(2026, 10, 7)


def listing_page(title: str, price: str, *, detail: bool = True) -> tuple[Document, WebListingCandidate]:
    content = f"{title}\nMỹ Đình, Hà Nội\nGiá: {price}\nĐăng 2 ngày trước"
    page = Document(
        page_content=content,
        metadata={
            "source": f"https://example.com/listing/{title.replace(' ', '-')}",
            "title": title,
            "page_read": True,
        },
    )
    candidate = WebListingCandidate(
        source_index=1,
        is_detail_page=detail,
        title=title,
        property_type="house",
        location_text="Mỹ Đình, Hà Nội",
        price_text=price,
        posted_text="2 ngày trước",
    )
    return page, candidate


class ListingEvidenceTests(unittest.TestCase):
    def test_exclusive_price_ceiling_rejects_boundary_and_above(self):
        budget = explicit_price_range("giá nhà Mỹ Đình Hà Nội dưới 5 tỉ mới nhất")
        self.assertIsNotNone(budget)
        request = WebRequest(
            search_query="nhà Mỹ Đình dưới 5 tỷ",
            kind="listings",
            location="Mỹ Đình, Hà Nội",
            property_type="house",
            price_million=budget,
            sort_newest=True,
        )
        for price, expected in (("4,8 tỷ", 1), ("5 tỷ", 0), ("6,99 tỷ", 0), ("5 - 7 tỷ", 0)):
            with self.subTest(price=price):
                page, candidate = listing_page("Nhà Mỹ Đình", price)
                self.assertEqual(
                    len(verify_listings([page], WebListingBatch(listings=[candidate]), request, TODAY)),
                    expected,
                )

    def test_requires_detail_page_and_sourced_required_fields(self):
        request = WebRequest(
            search_query="nhà Mỹ Đình", kind="listings", location="Mỹ Đình, Hà Nội",
        )
        page, candidate = listing_page("Nhà Mỹ Đình", "4,8 tỷ", detail=False)
        self.assertEqual(verify_listings([page], WebListingBatch(listings=[candidate]), request, TODAY), [])
        candidate.is_detail_page = True
        candidate.price_text = "3 tỷ"
        self.assertEqual(verify_listings([page], WebListingBatch(listings=[candidate]), request, TODAY), [])

    def test_category_page_cannot_supply_an_individual_ad(self):
        request = WebRequest(search_query="nhà Mỹ Đình", kind="listings", location="Mỹ Đình, Hà Nội")
        page, candidate = listing_page("Nhà Mỹ Đình", "4,8 tỷ")
        page.metadata["title"] = "Mua bán nhà Hà Nội giá từ 3 đến 5 tỷ"
        self.assertEqual(verify_listings([page], WebListingBatch(listings=[candidate]), request, TODAY), [])
        page.metadata["title"] = candidate.title
        page.metadata["source"] = "https://example.com/mua-ban-nha-ha-noi-gia-tu-3-ty-den-5-ty"
        self.assertEqual(verify_listings([page], WebListingBatch(listings=[candidate]), request, TODAY), [])

    def test_budget_parser_uses_numbers_from_the_question(self):
        self.assertEqual(explicit_price_range("căn hộ dưới 3,5 tỷ").max_value, 3500)
        between = explicit_price_range("nhà từ 2 đến 4 tỷ")
        self.assertEqual((between.min_value, between.max_value), (2000, 4000))
        both = explicit_price_range("nhà trên 3 tỷ và dưới 5 tỷ")
        self.assertEqual((both.min_value, both.max_value), (3000, 5000))
        self.assertEqual(
            explicit_location("giá nhà khu vực mĩ đình hà nội dưới 5 tỉ mới nhất"),
            "mĩ đình hà nội",
        )


class LiveDDGSTests(unittest.TestCase):
    def test_search_and_read_real_page(self):
        pages = asyncio.run(search_web("site:example.com Example Domain"))
        self.assertTrue(pages)
        self.assertTrue(any(
            page.metadata["page_read"] and len(page.page_content) > 20
            and "example.com" in page.metadata["source"]
            for page in pages
        ))

    def test_search_timeout_returns_no_pages(self):
        def slow_search(*args):
            time.sleep(1)

        with patch("src.tools.web_search._search_web", side_effect=slow_search), \
             patch("src.tools.web_search.WEB_SEARCH_TIMEOUT_SECONDS", 0.01):
            pages = asyncio.run(search_web("slow query"))
        self.assertEqual(pages, [])


if __name__ == "__main__":
    unittest.main()
