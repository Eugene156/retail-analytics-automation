"""Allowlisted HTTP completion logs; no payload/credential inspection or tracing."""
from datetime import datetime, timezone
import json
import logging
import sys
from time import perf_counter
from uuid import uuid4

LOGGER = logging.getLogger('raa.safe_http')
if not LOGGER.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(message)s'))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False

ROUTES = frozenset({
    '/healthz', '/readyz', '/openapi.json', '/api/v1/calculations/comparison',
    '/api/v1/report-requests', '/api/v1/cases/{case_id}',
    '/api/v1/cases/{case_id}/revisions/{revision}',
    '/api/v1/cases/{case_id}/revisions/{revision}/preview',
    '/api/p2/sales-kpis', '/api/p2/data-quality',
})
SERVICES = frozenset({'retail-api', 'p2-read-api', 'logging-demo'})


class SafeRequestLogging:
    def __init__(self, app, service):
        if service not in SERVICES:
            raise ValueError('Unknown logging service')
        self.app, self.service = app, service

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id, started = str(uuid4()), perf_counter()
        scope.setdefault('state', {})['http_request_id'] = request_id
        status, outcome = 0, 'completed'
        response_started = False

        async def correlated_send(message):
            nonlocal status, response_started
            if message['type'] == 'http.response.start':
                status = message['status']
                response_started = True
                # Never echo caller-provided correlation headers or mutate body.
                message = dict(message)
                message['headers'] = [(k, v) for k, v in message.get('headers', [])
                                      if k.lower() != b'x-request-id']
                message['headers'].append((b'x-request-id', request_id.encode('ascii')))
            await send(message)

        try:
            return await self.app(scope, receive, correlated_send)
        except BaseException:
            outcome = 'interrupted'
            if not status:
                status = 500
            raise
        finally:
            template = getattr(scope.get('route'), 'path', None)
            method = scope.get('method', 'OTHER')
            event = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'event': 'http_request_completed', 'service': self.service,
                'http_request_id': request_id,
                'method': method if method in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'} else 'OTHER',
                'route': template if template in ROUTES else 'unmatched_or_other',
                'status_code': status,
                'response_started': response_started,
                'duration_ms': round((perf_counter() - started) * 1000, 3),
                'outcome': outcome,
            }
            try:
                LOGGER.info(json.dumps(event, separators=(',', ':'), allow_nan=False))
            except Exception:
                # A failing log sink cannot alter authorization or response behavior.
                pass


def demo():
    """Synthetic ASGI event only: no HTTP connection, secrets or database."""
    import asyncio
    from types import SimpleNamespace

    async def app(scope, receive, send):
        scope['route'] = SimpleNamespace(path='/healthz')
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{"status":"ok"}'})

    async def send(message):
        pass

    async def receive():
        return {'type': 'http.request', 'body': b''}

    asyncio.run(SafeRequestLogging(app, 'logging-demo')(
        {'type': 'http', 'method': 'GET', 'path': '/healthz'}, receive, send))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', required=True)
    parser.parse_args()
    demo()
