#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from unittest.mock import patch
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

    def test_reuters_is_retained_as_reputable_reporting(self):
        self.assertIn("reuters.com", web_search.REPUTABLE_REPORTING_DOMAINS)
        labelled = web_search._claim_label_for_result(
            {
                "title": "Example current report",
                "description": "Reuters reports the verified event details.",
                "url": "https://www.reuters.com/world/example-report-2026-10-16/",
            },
            self.clock,
        )
        self.assertEqual(labelled["domain"], "reuters.com")
        self.assertEqual(labelled["source_relation"], "reputable_reporting")
        self.assertEqual(labelled["label"], "credibly_reported")


class WebSearchRoutingTests(unittest.TestCase):
    setUp = WebSearchPolicyTests.setUp
    def settings(self, **overrides):
        tool = web_search.Tools()
        values = tool.valves.model_dump()
        values.update(BRAVE_API_KEY='synthetic-key', LOCALITY='Poole', GOOGLE_NEWS=False,
                      UPSTREAM_SOURCES=False, CUSTODY_CHECKS=False, F1_SCHEDULE=False)
        values.update(overrides)
        return values

    def run_search(self, query, *, count=3, freshness='auto', mode='auto', **settings):
        with patch.object(web_search, '_current_time_context', return_value=self.clock):
            return json.loads(web_search.Tools()._run_search(
                query, count, freshness, mode, False, self.settings(**settings)))

    @staticmethod
    def items(count=3, prefix='fixture', date='2026-10-07'):
        return [{'title': f'Synthetic report {prefix} {i}',
                 'description': 'A synthetic discovery snippet.',
                 'url': f'https://example.org/articles/{prefix}-{i}',
                 'page_age': date} for i in range(count)]

    @staticmethod
    def response(status=200, items=None, headers=None):
        response = web_search.requests.Response()
        response.status_code = status
        response.headers.update(headers or {})
        response._content_consumed = True
        response._content = json.dumps({'web': {'results': items or []}}).encode()
        return response

    def test_routing_table(self):
        cases = [
            ('python 3.13 release notes', 'web', None, False),
            ('Python update dictionary', 'web', None, False),
            ('new Python virtual environment', 'web', None, False),
            ('New York museums', 'web', None, False),
            ('New Zealand history', 'web', None, False),
            ('New Jersey railway map', 'web', None, False),
            ('live music recordings', 'web', None, False),
            ('live USB persistence', 'web', None, False),
            ('current transformer wiring', 'web', None, False),
            ('current account definition', 'web', None, False),
            ('release valve diagram', 'web', None, False),
            ('SQL update syntax', 'web', None, False),
            ('now function in PostgreSQL', 'web', None, False),
            ('latest Python version', 'web', 'pm', False),
            ('current Python version', 'web', 'pm', False),
            ('current version of Python', 'web', 'pm', False),
            ('recent compiler benchmarks', 'web', 'pm', False),
            ('weather today', 'web', 'pd', False),
            ('train status right now', 'live', 'pd', True),
            ('UK news', 'news', 'pw', True),
            ('latest EU news', 'news', 'pw', True),
            ('world news', 'headlines', 'pw', True),
            ('headlines', 'headlines', 'pw', True),
            ('local news Poole', 'local', 'pw', True),
            ('news near me', 'local', 'pw', True),
            ('F1 live updates', 'live', 'pd', True),
            ('live election results', 'live', 'pd', True),
            ('Python 2024 release notes', 'web', None, False),
            ('UK news 2024', 'web', None, False),
            ('Formula 1 2025 calendar', 'web', None, False),
            ('scores of people displaced by floods', 'web', None, False),
            ('football scores', 'live', 'pd', True),
            ('BBC News website redesign history', 'web', None, False),
            ('history of local news', 'web', None, False),
            ('latest BBC news on museum history', 'news', 'pw', True),
            ('VS Code release notes', 'web', None, False),
            ('history curriculum news', 'news', 'pw', True),
            ('historical building news', 'news', 'pw', True),
            ('archaeology origins news', 'news', 'pw', True),
            ('origins of BBC News', 'web', None, False),
        ]
        for query, mode, freshness, dated in cases:
            with self.subTest(query=query), \
                 patch.object(web_search, '_brave_results', return_value=self.items(12)) as brave:
                result = self.run_search(query)
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['mode'], mode)
                self.assertEqual(result['freshness'], freshness)
                self.assertEqual(self.clock['date'] in result['query'], dated)
                self.assertEqual(brave.call_args_list[0].args[3], freshness)

    def test_sparse_automatic_search_retries_once_without_filter(self):
        with patch.object(web_search.requests, 'request', side_effect=[
            self.response(items=self.items(1)), self.response(items=self.items(3)),
        ]) as request:
            result = self.run_search('latest Python version')
        self.assertEqual(len(result['results']), 3)
        self.assertTrue(result['freshness_relaxed'])
        self.assertEqual(result['query'], 'latest Python version')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].kwargs['params']['freshness'], 'pm')
        self.assertNotIn('freshness', request.call_args_list[1].kwargs['params'])
        self.assertFalse(request.call_args.kwargs['allow_redirects'])

    def test_explicit_freshness_is_never_relaxed(self):
        for freshness in ('pd', 'pw', 'pm', 'py', 'none', '2024-01-01to2024-12-31'):
            with self.subTest(freshness=freshness), \
                 patch.object(web_search.requests, 'request', return_value=self.response(items=self.items(1))) as request:
                result = self.run_search('Python release notes', freshness=freshness)
                self.assertFalse(result['freshness_relaxed'])
                self.assertEqual(request.call_count, 1)

    def test_news_fallback_keeps_age_checks(self):
        with patch.object(web_search.requests, 'request', side_effect=[
            self.response(items=self.items(1)),
            self.response(items=self.items(3, 'old', '2025-01-01')),
        ]):
            result = self.run_search('UK news')
        self.assertTrue(result['freshness_relaxed'])
        self.assertEqual(len(result['results']), 1)
        self.assertTrue(result['results'][0]['claim_discipline']['usable_as_current_news'])

    def test_403_blocks_further_provider_calls(self):
        with patch.object(web_search.requests, 'request', return_value=self.response(403)) as request:
            result = self.run_search('world news')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result['diagnostics']['http_requests'], 1)
        self.assertFalse(result['ok'])
        self.assertTrue(any('provider rejection' in warning for warning in result['warnings']))

    def test_request_budget_retains_baseline_without_extra_network(self):
        with patch.object(web_search.requests, 'request', return_value=self.response(items=self.items(1))) as request:
            result = self.run_search('latest Python version', MAX_REQUESTS=1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['diagnostics']['budget_exhausted'])
        self.assertFalse(result['freshness_relaxed'])

    def test_expired_time_budget_retains_baseline(self):
        now = [100.0]
        def request(*args, **kwargs):
            now[0] = 200.0
            return self.response(items=self.items(1))
        with patch.object(web_search.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(web_search.requests, 'request', side_effect=request) as fetch:
            result = self.run_search('latest Python version', TIME_BUDGET_SECONDS=5)
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(result['diagnostics']['budget_exhausted'])
        self.assertEqual(len(result['results']), 1)

    def test_failed_fallback_retains_filtered_results(self):
        with patch.object(web_search.requests, 'request', side_effect=[
            self.response(items=self.items(1)), self.response(403),
        ]):
            result = self.run_search('latest Python version')
        self.assertEqual(len(result['results']), 1)
        self.assertFalse(result['freshness_relaxed'])
        self.assertTrue(any('HTTP 403' in warning for warning in result['warnings']))

    def test_web_latest_retains_older_results_and_uses_web_metadata(self):
        with patch.object(web_search.requests, 'request', side_effect=[
            self.response(items=[]), self.response(items=self.items(1, date='2026-10-04')),
        ]):
            result = self.run_search('bitcoin latest price', count=1, mode='web')
        self.assertTrue(result['freshness_relaxed'])
        self.assertEqual(len(result['results']), 1)
        discipline = result['results'][0]['claim_discipline']
        self.assertIsNone(discipline['current_news_window_days'])
        self.assertFalse(discipline['background_only'])
        self.assertEqual(discipline['source_age_days'], 3)

    def test_missing_locality_only_degrades_automatic_mode(self):
        with patch.object(web_search.requests, 'request', return_value=self.response(items=self.items(1))) as request:
            result = self.run_search('news near me', count=1, LOCALITY='')
        self.assertTrue(result['ok'])
        self.assertEqual(result['mode'], 'news')
        self.assertNotIn('near me', result['query'])
        self.assertNotIn('Poole', result['query'])
        self.assertTrue(any('No locality configured' in warning for warning in result['warnings']))
        self.assertEqual(request.call_count, 1)
        with patch.object(web_search.requests, 'request') as request:
            result = self.run_search('news near me', mode='local', LOCALITY='')
        self.assertFalse(result['ok'])
        request.assert_not_called()

    def test_compact_output_hoists_rules_and_preserves_evidence(self):
        tool = web_search.Tools()
        output = []
        for compact in (False, True):
            with patch.object(web_search, '_current_time_context', return_value=self.clock), \
                 patch.object(web_search, '_brave_results', return_value=self.items(12)):
                output.append(tool._run_search('UK news', 10, 'auto', 'news', False,
                                               self.settings(COMPACT_OUTPUT=compact)))
        rich, compact = map(json.loads, output)
        self.assertLess(len(output[1]), len(output[0]) * 0.8)
        self.assertEqual(rich['response_policy'], compact['response_policy'])
        self.assertIn('untrusted_content', compact['response_policy'])
        for before, after in zip(rich['results'], compact['results']):
            restored = dict(after['claim_discipline'], **compact['claim_discipline_rules'])
            self.assertEqual(before['claim_discipline'], restored)
            self.assertEqual(before['url'], after['url'])
            self.assertEqual(before['claim_label'], after['claim_label'])
            self.assertEqual(after['evidence_scope'], 'search_snippet')


class WebSearchHeuristicTests(unittest.TestCase):
    setUp = WebSearchPolicyTests.setUp

    def test_month_names_and_modal_language_have_distinct_labels(self):
        cases = [
            ('Figures for 3 May 2025 show volume growth', 'primary_source_unverified'),
            ('May 2025 figures show volume growth', 'primary_source_unverified'),
            ('Figures for May show volume growth', 'primary_source_unverified'),
            ('May data show volume growth', 'primary_source_unverified'),
            ('Theresa May said the figures were published', 'primary_source_unverified'),
            ('The bank may cut rates after reviewing May data', 'rumour/speculation'),
            ('The bank may not raise rates', 'rumour/speculation'),
            ('The bank may have revised its forecast', 'rumour/speculation'),
            ('The suspect may face charges', 'rumour/speculation'),
            ('The suspect may be released', 'rumour/speculation'),
            ('The bank could cut rates', 'rumour/speculation'),
            ('The bank reportedly revised its forecast', 'rumour/speculation'),
        ]
        for text, label in cases:
            with self.subTest(text=text):
                result = web_search._claim_label_for_result({
                    'title': 'Economic bulletin', 'description': text,
                    'url': 'https://www.ons.gov.uk/economy/articles/fixture',
                }, self.clock)
                self.assertEqual(result['label'], label)
                self.assertEqual(result['source_relation'], 'official_source')
                self.assertFalse(result['verified'])

    def test_vs_code_is_not_an_opponent_pairing(self):
        for query, expected in [('VS Code release notes', False),
                                 ('vs code extensions', False),
                                 ('Arsenal vs Chelsea', True),
                                 ('VS Code: Arsenal vs Chelsea fixture viewer', True)]:
            with self.subTest(query=query):
                result = web_search._freshness_for_result({}, query, self.clock)
                self.assertEqual(result['same_record_validation'], expected)

    def test_upstream_title_match_does_not_establish_domain_ownership(self):
        source = {'title': 'Woodland Trust annual report', 'description': 'Annual report figures'}
        hint = {'source_name': 'Woodland Trust'}
        for domain, accepted in [('woodlandtrust.org.uk', True), ('random-reports.invalid', False)]:
            with self.subTest(domain=domain):
                candidate = {**source, 'url': f'https://{domain}/articles/annual-report',
                             'page_age': self.clock['date']}
                score = web_search._upstream_candidate_score(candidate, source, hint, self.clock)
                self.assertEqual(score >= 0.62, accepted)


if __name__ == "__main__":
    unittest.main()
