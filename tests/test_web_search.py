#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rhizome_web_search", ROOT / "components/openwebui-tools/web_search.py"
)
web_search = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(web_search)


class WebSearchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.clock = {
            "date": "2026-10-07",
            "year": "2026",
            "timezone": "Europe/London",
            "iso": "2026-10-07T17:00:00+01:00",
            "date_long": "Wednesday, 07 October 2026",
        }

    def test_false_today_date_is_replaced(self):
        grounded, changed = web_search._ground_today_date(
            "Today is August 9 2026, latest UK news", self.clock
        )
        self.assertTrue(changed)
        self.assertIn("Today 2026-10-07", grounded)
        self.assertNotIn("August 9", grounded)
        self.assertEqual(web_search._build_search_query(grounded, self.clock), grounded)

    def test_historical_date_subject_is_not_rewritten(self):
        query = "latest reporting about August 9 2026"
        grounded, changed = web_search._ground_today_date(query, self.clock)
        self.assertFalse(changed)
        self.assertEqual(grounded, query)

    def test_news_policy_uses_event_centric_symmetric_framing(self):
        policy = web_search._response_policy(is_news=True, is_main_news=True)
        framing = policy["political_framing"]
        self.assertIn("event-centric", framing["event_centric"])
        self.assertIn("symmetrical verbs", framing["symmetric_verbs"])
        self.assertIn("dominates", framing["dominance_check"])
        self.assertIn("balance", policy)

    def test_non_news_policy_does_not_inject_political_rules(self):
        policy = web_search._response_policy(is_news=False, is_main_news=False)
        self.assertNotIn("political_framing", policy)
        self.assertNotIn("balance", policy)


if __name__ == "__main__":
    unittest.main()
