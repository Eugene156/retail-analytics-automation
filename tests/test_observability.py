"""Synthetic ASGI tests: correlation/privacy/response preservation; no services."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

from api.observability import LOGGER, SafeRequestLogging


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, app, scope=None):
        sent, events = [], []
        scope = scope or {'type': 'http', 'method': 'GET', 'path': '/healthz'}

        async def receive():
            return {'type': 'http.request', 'body': b'sensitive request payload'}

        async def send(message):
            sent.append(message)

        with patch.object(LOGGER, 'info', side_effect=events.append):
            await SafeRequestLogging(app, 'retail-api')(scope, receive, send)
        return sent, [json.loads(e) for e in events], scope

    async def test_server_id_correlates_response_and_single_event(self):
        async def app(scope, receive, send):
            scope['route'] = SimpleNamespace(path='/api/v1/cases/{case_id}')
            await send({'type': 'http.response.start', 'status': 200,
                        'headers': [(b'x-request-id', b'untrusted'), (b'cache-control', b'no-store')]})
            await send({'type': 'http.response.body', 'body': b'sensitive response'})
        sent, events, scope = await self.invoke(app)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(str(UUID(event['http_request_id'])), event['http_request_id'])
        self.assertEqual(dict(sent[0]['headers'])[b'x-request-id'].decode(), event['http_request_id'])
        self.assertEqual(scope['state']['http_request_id'], event['http_request_id'])
        self.assertEqual(event['route'], '/api/v1/cases/{case_id}')
        self.assertGreaterEqual(event['duration_ms'], 0)
        self.assertEqual(sent[1]['body'], b'sensitive response')
        self.assertEqual(dict(sent[0]['headers'])[b'cache-control'], b'no-store')

    async def test_private_inputs_and_unmatched_paths_are_never_logged(self):
        private = 'synthetic-private-value'
        scope = {'type': 'http', 'method': private, 'path': '/'+private,
                 'query_string': private.encode(), 'client': (private, 1),
                 'headers': [(b'authorization', private.encode()), (b'x-request-id', private.encode())]}
        async def app(scope, receive, send):
            await receive()
            await send({'type': 'http.response.start', 'status': 401, 'headers': []})
            await send({'type': 'http.response.body', 'body': private.encode()})
        _, events, _ = await self.invoke(app, scope)
        text = json.dumps(events)
        self.assertNotIn(private, text)
        self.assertNotIn('sensitive', text)
        self.assertEqual(events[0]['route'], 'unmatched_or_other')
        self.assertEqual(events[0]['method'], 'OTHER')
        self.assertEqual(events[0]['status_code'], 401)
        self.assertEqual(set(events[0]), {'timestamp', 'event', 'service', 'http_request_id',
                                        'method', 'route', 'status_code', 'response_started', 'duration_ms', 'outcome'})

    async def test_early_exception_logs_once_without_exception_text(self):
        events = []
        async def app(scope, receive, send):
            raise RuntimeError('private-connection-string')
        with patch.object(LOGGER, 'info', side_effect=events.append):
            with self.assertRaises(RuntimeError):
                await SafeRequestLogging(app, 'retail-api')(
                    {'type': 'http', 'method': 'POST'}, None, None)
        self.assertEqual(len(events), 1)
        self.assertNotIn('private', events[0])
        self.assertEqual(json.loads(events[0])['status_code'], 500)
        self.assertFalse(json.loads(events[0])['response_started'])

    async def test_non_http_scope_is_unchanged_and_not_logged(self):
        seen = []
        async def app(scope, receive, send): seen.append(scope)
        scope = {'type': 'lifespan'}
        _, events, returned = await self.invoke(app, scope)
        self.assertEqual(events, [])
        self.assertEqual(seen, [scope])
        self.assertEqual(returned, scope)

    async def test_failed_log_sink_does_not_change_response(self):
        sent = []
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 422, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'unchanged'})
        async def send(message): sent.append(message)
        with patch.object(LOGGER, 'info', side_effect=OSError('sink unavailable')):
            await SafeRequestLogging(app, 'retail-api')({'type': 'http', 'method': 'POST'}, None, send)
        self.assertEqual(sent[-1]['body'], b'unchanged')
        self.assertEqual(sent[0]['status'], 422)

    async def test_simultaneous_requests_have_separate_ids(self):
        import asyncio
        async def app(scope, receive, send):
            await asyncio.sleep(0)
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        events = []
        async def request():
            sent = []
            async def send(message): sent.append(message)
            await SafeRequestLogging(app, 'retail-api')({'type': 'http', 'method': 'GET'}, None, send)
            return dict(sent[0]['headers'])[b'x-request-id'].decode()
        with patch.object(LOGGER, 'info', side_effect=events.append):
            ids = await asyncio.gather(*(request() for _ in range(3)))
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual({json.loads(e)['http_request_id'] for e in events}, set(ids))

    def test_factory_registration_is_outermost_and_no_incoming_id_is_trusted(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('main.py', 'p2_demo.py'):
            tree = ast.parse((root/'api'/name).read_text())
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == ('create_app' if name == 'main.py' else 'application'))
            call = fn.body[-2].value
            self.assertEqual(call.func.attr, 'add_middleware')
            self.assertEqual(call.args[0].id, 'SafeRequestLogging')
