"""Focused offline checks of the presentation surface and unchanged API boundary."""
import asyncio
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from api.main import Settings, create_app
from api.overview import ASSETS, FILES, OverviewMiddleware

ROOT = Path(__file__).resolve().parents[1]


def request(app, path='/overview', method='GET', headers=None, query=b''):
    messages = []
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(message):
        messages.append(message)
    asyncio.run(app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'scheme': 'http', 'method': method, 'path': path, 'raw_path': path.encode(),
        'query_string': query, 'headers': headers if headers is not None else [(b'host', b'127.0.0.1:18090')],
        'client': ('127.0.0.1', 1), 'server': ('127.0.0.1', 18090)}, receive, send))
    start = next(m for m in messages if m['type'] == 'http.response.start')
    return start['status'], b''.join(m.get('body', b'') for m in messages), dict(start['headers'])


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.disabled = 0; self.modules = 0; self.links = []; self.ids = set(); self.facts = {}
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'button' and 'disabled' in a: self.disabled += 1
        if tag == 'article' and 'module' in a.get('class', '').split(): self.modules += 1
        if 'id' in a: self.ids.add(a['id'])
        if 'data-fact' in a: self.facts[a['data-fact']] = a['data-value']
        for key in ('src', 'href'):
            if key in a: self.links.append(a[key])


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Settings('a' * 64, 'unused'))

    def test_page_and_assets_load_without_auth_or_database(self):
        with patch('api.main.psycopg.connect') as db:
            for path, (_, media) in FILES.items():
                with self.subTest(path=path):
                    code, body, headers = request(self.app, path)
                    self.assertEqual(code, 200)
                    self.assertTrue(body)
                    self.assertIn(media.encode(), headers[b'content-type'])
                    self.assertIn(b'x-request-id', headers)
            db.assert_not_called()

    def test_security_headers_and_head_preserve_representation_length(self):
        code, body, headers = request(self.app)
        head, empty, head_headers = request(self.app, method='HEAD')
        self.assertEqual((head, empty), (200, b''))
        self.assertEqual(head_headers[b'content-length'], str(len(body)).encode())
        self.assertEqual(headers[b'cache-control'], b'no-store')
        self.assertIn(b"connect-src 'none'", headers[b'content-security-policy'])
        self.assertIn(b"frame-ancestors 'none'", headers[b'content-security-policy'])
        self.assertNotIn(b'set-cookie', headers)

    def test_host_origin_and_query_remain_narrow(self):
        cases = [([], b''), ([(b'host', b'external.invalid')], b''),
            ([(b'host', b'localhost:18090')], b''),
            ([(b'host', b'127.0.0.1:18090')] * 2, b''),
            ([(b'host', b'127.0.0.1:18090'), (b'origin', b'https://external.invalid')], b''),
            ([(b'host', b'127.0.0.1:18090')], b'token=synthetic')]
        for headers, query in cases:
            with self.subTest(headers=headers, query=query):
                self.assertEqual(request(self.app, headers=headers, query=query)[0], 400)

    def test_methods_and_file_allowlist_never_reach_database(self):
        with patch('api.main.psycopg.connect') as db:
            for method in ('POST', 'PUT', 'DELETE', 'OPTIONS'):
                self.assertEqual(request(self.app, method=method)[0], 405)
            for path in ('/overview/assets/../../main.py', '/overview/assets/main.py', '/overview/secrets', '/overview/unknown'):
                self.assertEqual(request(self.app, path)[0], 404)
            db.assert_not_called()

    def test_exact_tracking_query_redirects_get_and_head_to_clean_entry(self):
        with patch('api.main.psycopg.connect') as db:
            for path in ('/overview', '/overview/'):
                for method in ('GET', 'HEAD'):
                    with self.subTest(path=path, method=method):
                        code, body, headers = request(self.app, path, method, query=b'utm_source=chatgpt.com')
                        self.assertEqual((code, body), (303, b''))
                        self.assertEqual(headers[b'location'], b'/overview')
                        self.assertEqual(headers[b'cache-control'], b'no-store')
                        self.assertIn(b"connect-src 'none'", headers[b'content-security-policy'])
                        self.assertEqual(request(self.app, headers[b'location'].decode())[0], 200)
            db.assert_not_called()

    def test_duplicate_extra_and_unexpected_tracking_queries_are_rejected(self):
        queries = [b'utm_source=chatgpt.com&utm_source=chatgpt.com',
            b'utm_source=chatgpt.com&utm_source=other',
            b'utm_source=other&utm_source=chatgpt.com',
            b'utm_source=chatgpt.com&extra=1', b'extra=1&utm_source=chatgpt.com',
            b'utm_source=other', b'utm_source=', b'utm_source', b'utm_source=chatgpt.com&',
            b'utm_source=chatgpt%2Ecom', b'%75tm_source=chatgpt.com', b'anything=1']
        for query in queries:
            with self.subTest(query=query):
                code, _, headers = request(self.app, query=query)
                self.assertEqual(code, 400)
                self.assertNotIn(b'location', headers)

    def test_tracking_query_does_not_bypass_host_or_origin_checks(self):
        cases = [[(b'host', b'localhost:18090')], [(b'host', b'external.invalid')],
            [(b'host', b'127.0.0.1:18090')] * 2,
            [(b'host', b'127.0.0.1:18090'), (b'origin', b'https://external.invalid')],
            [(b'host', b'127.0.0.1:18090'), (b'origin', b'null')]]
        for headers in cases:
            with self.subTest(headers=headers):
                code, _, returned = request(self.app, headers=headers, query=b'utm_source=chatgpt.com')
                self.assertEqual(code, 400)
                self.assertNotIn(b'location', returned)

    def test_tracking_exception_is_only_for_read_only_html_entry(self):
        for path in ('/overview/assets/overview.css', '/overview/assets/overview.js', '/overview/unknown'):
            with self.subTest(path=path):
                self.assertEqual(request(self.app, path, query=b'utm_source=chatgpt.com')[0], 400)
        for method in ('POST', 'PUT', 'DELETE', 'OPTIONS'):
            with self.subTest(method=method):
                self.assertEqual(request(self.app, method=method, query=b'utm_source=chatgpt.com')[0], 405)

    def test_existing_api_routes_still_require_bearer(self):
        with patch('api.main.psycopg.connect') as db:
            self.assertEqual(request(self.app, '/healthz')[0], 200)
            self.assertEqual(request(self.app, '/readyz')[0], 401)
            self.assertEqual(request(self.app, '/openapi.json')[0], 401)
            self.assertEqual(request(self.app, '/api/v1/report-requests', 'POST')[0], 401)
            headers = [(b'host', b'127.0.0.1:18090'), (b'authorization', b'Bearer ' + b'a' * 64)]
            self.assertEqual(request(self.app, '/openapi.json', headers=headers)[0], 200)
            db.assert_not_called()

    def test_only_overview_navigation_and_local_resources(self):
        page = Page(); page.feed((ASSETS / 'index.html').read_text(encoding='utf-8'))
        self.assertEqual((page.disabled, page.modules), (0, 5))
        for link in page.links:
            if link.startswith('#'):
                self.assertIn(link[1:], page.ids)
            else:
                self.assertTrue(link in FILES or link == "http://127.0.0.1:18082/portal/f2")
        source = (ASSETS / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('<form', source)
        self.assertIn('Saved project evidence', source)
        self.assertIn('Hosted CI pending', source)

    def test_evidence_figures_have_existing_receipts(self):
        page = (ASSETS / 'index.html').read_text(encoding='utf-8')
        p1 = json.loads((ROOT / 'evidence/p12_human_approval.json').read_text())
        live = json.loads((ROOT / 'evidence/p6_live_validation.json').read_text())
        repair = json.loads((ROOT / 'evidence/p6_combined_repair.json').read_text())
        rag = json.loads((ROOT / 'evidence/p4_rag_runtime.json').read_text())['database']
        self.assertIn(f"{p1['source_rows']:,}", page)
        self.assertEqual(live['passed'] + len(repair['cases']), 8)
        self.assertEqual(repair['status'], 'PASS')
        self.assertIn('Mixed original + repaired runs', page)
        stages = {'P1'} | {case['case'].split('-')[0] for case in live['cases']}
        parsed = Page(); parsed.feed(page)
        self.assertEqual(parsed.facts, {
            'workflow-modules': str(len(stages)), 'ai-evaluation': '8/8',
            'rag-documents': str(rag['sources']), 'vector-chunks': str(rag['chunks']),
            'source-rows': str(p1['source_rows'])})
        self.assertEqual(rag['dimensions'], 384)
        self.assertIn('384D embeddings', page)

    def test_compact_layout_preserves_noninteractive_previews_and_technology_tiles(self):
        page = (ASSETS / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(page.count('class="preview '), 5)
        self.assertEqual(page.count('<dt>'), 9)
        self.assertIn('WELCOME TO', page)
        self.assertIn('Process illustrations · Not execution results', page)
        for obsolete in ('Facts first.', 'Demo Ready', '<input', 'class="capabilities"'):
            self.assertNotIn(obsolete, page)

    def test_no_network_or_secret_storage_in_javascript(self):
        source = (ASSETS / 'overview.js').read_text(encoding='utf-8')
        for forbidden in ('fetch(', 'XMLHttpRequest', 'WebSocket', 'localStorage', 'sessionStorage', 'Authorization', 'Bearer '):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
