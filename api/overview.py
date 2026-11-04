"""Fixed, loopback-only presentation surface; no credentials, DB or workflow calls."""
from pathlib import Path

from starlette.responses import Response

ASSETS = Path(__file__).with_name('overview_assets')
FILES = {
    '/overview': ('index.html', 'text/html'),
    '/overview/': ('index.html', 'text/html'),
    '/overview/assets/overview.css': ('overview.css', 'text/css'),
    '/overview/assets/overview.js': ('overview.js', 'text/javascript'),
}
ORIGIN = b'http://127.0.0.1:18090'
HEADERS = {
    'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'none'; style-src 'self'; script-src 'self'; "
        "img-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'X-Frame-Options': 'DENY',
}


class OverviewMiddleware:
    """Only public overview files bypass API auth; every other path passes intact."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not (path == '/overview' or path.startswith('/overview/')):
            return await self.app(scope, receive, send)
        def values(name):
            return [v for k, v in scope['headers'] if k.lower() == name]
        status, data, media = 200, b'', 'text/plain'
        extra = {}
        query = scope.get('query_string', b'')
        tracking_entry = path in ('/overview', '/overview/') and query == b'utm_source=chatgpt.com'
        if (values(b'host') != [b'127.0.0.1:18090']
                or values(b'origin') not in ([], [ORIGIN])):
            status = 400
        elif query and not tracking_entry:
            status = 400
        elif scope['method'] not in ('GET', 'HEAD'):
            status = 405
            extra['Allow'] = 'GET, HEAD'
        elif tracking_entry:
            # Exact raw match rejects duplicate/extra parameters; never reflect a supplied URL.
            return await Response(status_code=303, headers={**HEADERS, 'Location': '/overview'})(scope, receive, send)
        elif path not in FILES:
            status = 404
        else:
            filename, media = FILES[path]
            try:
                data = (ASSETS / filename).read_bytes()
            except OSError:
                status, media = 503, 'text/plain'
        if status != 200:
            data = b'Overview unavailable.'
        response = Response(data, status, headers={**HEADERS, **extra}, media_type=media)
        if scope['method'] == 'HEAD':
            response.body = b''
        return await response(scope, receive, send)
