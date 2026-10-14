# SPDX-License-Identifier: LicenseRef-Personal-NonCommercial
# Copyright (c) 2026 Alexander Kurach. See ../LICENSE.
"""Offline regression checks for pagination and failure semantics."""
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from iss_get import collect, fetch, table_rows


def fake(pages):
    def fetcher(url, timeout):
        start = int(parse_qs(urlsplit(url).query).get("start", [0])[0])
        return pages[start], {"url": url, "http_status": 200, "passport_marker": "denied"}
    return fetcher


def page(values, index=None, total=None):
    result = {"history": {"columns": ["CLOSE"], "data": [[v] for v in values]}}
    if total is not None:
        result["history.cursor"] = {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[index, total, 100]]}
    return result


class IssTests(unittest.TestCase):
    def get(self, pages, **kwargs):
        with patch("iss_get.time.sleep"):
            return collect("/iss/example.json", {}, "history", True, fetcher=fake(pages), **kwargs)

    def test_null_and_dynamic_columns(self):
        self.assertEqual(table_rows({"columns": ["B", "A"], "data": [[None, 0]]}), [{"B": None, "A": 0}])

    def test_cursor_uses_actual_row_count(self):
        result = self.get({0: page([1, None], 0, 3), 2: page([3], 2, 3)})
        self.assertEqual(result["blocks"]["history"], [{"CLOSE": 1}, {"CLOSE": None}, {"CLOSE": 3}])
        self.assertTrue(result["paging"]["complete"])

    def test_short_page_without_cursor_is_not_end(self):
        result = self.get({0: page([1]), 1: page([2]), 2: page([])})
        self.assertEqual(len(result["sources"]), 3)
        self.assertTrue(result["paging"]["complete"])

    def test_page_limit_is_partial(self):
        result = self.get({0: page([1], 0, 2)}, max_pages=1)
        self.assertFalse(result["paging"]["complete"])
        self.assertEqual(result["paging"]["next_start"], 1)

    def test_missing_block_is_not_empty(self):
        with self.assertRaisesRegex(ValueError, "Missing expected block"):
            self.get({0: {}})

    def test_repeated_page_fails(self):
        with self.assertRaisesRegex(ValueError, "Repeated page"):
            self.get({0: page([1]), 1: page([1])})

    def test_early_empty_page_fails(self):
        with self.assertRaisesRegex(ValueError, "Empty page before"):
            self.get({0: page([], 0, 2)})

    def test_cursor_total_change_fails(self):
        with self.assertRaisesRegex(ValueError, "TOTAL changed"):
            self.get({0: page([1], 0, 2), 1: page([2], 1, 3)})

    def test_bad_width_fails(self):
        with self.assertRaisesRegex(ValueError, "Row width"):
            table_rows({"columns": ["A"], "data": [[1, 2]]})

    def test_nonpaged_does_not_claim_completeness(self):
        result = collect("/iss/example.json", {}, fetcher=fake({0: page([1])}))
        self.assertIsNone(result["paging"]["complete"])

    def test_transient_failure_stops_after_two_attempts(self):
        error = HTTPError("https://iss.moex.com/iss/test.json", 503, "Unavailable", {}, None)
        with patch("iss_get.urlopen", side_effect=error) as request, patch("iss_get.time.sleep"):
            with self.assertRaisesRegex(ValueError, "HTTP 503"):
                fetch(error.url, 1)
        self.assertEqual(request.call_count, 2)

    def test_forbidden_is_not_retried(self):
        error = HTTPError("https://iss.moex.com/iss/test.json", 403, "Forbidden", {}, None)
        with patch("iss_get.urlopen", side_effect=error) as request:
            with self.assertRaisesRegex(ValueError, "HTTP 403"):
                fetch(error.url, 1)
        self.assertEqual(request.call_count, 1)

    def test_long_retry_after_is_reported_without_early_retry(self):
        error = HTTPError("https://iss.moex.com/iss/test.json", 429, "Limited", {"Retry-After": "120"}, None)
        with patch("iss_get.urlopen", side_effect=error) as request, patch("iss_get.time.sleep") as sleep:
            with self.assertRaisesRegex(ValueError, "Retry-After=120"):
                fetch(error.url, 1)
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
