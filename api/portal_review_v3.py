"""Isolated new-target service issuance and confirmed owner review, not deployment."""
from datetime import datetime
from hashlib import sha256
from html import escape
import json
import re
import secrets

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from api.main import GuardMiddleware
from api.portal import HEADERS, HEX, LEGACY_BOUNDARY, PortalGuard, digest
from api.portal_publication import IsolatedPortalPublicationStore, PortalOutcomeUncertain, _install_read_routes

STATUSES = {'pending_review', 'expired', 'approved_expired', 'approved_pending_publication', 'rejected', 'published', 'superseded'}


class IsolatedOwnerReview:
    decisions_enabled = True

    def __init__(self, reader, reviewer, issuer):
        if not all(isinstance(store, IsolatedPortalPublicationStore) for store in (reader, reviewer, issuer)) \
                or len({store.database for store in (reader, reviewer, issuer)}) != 1 \
                or len({store.login for store in (reader, reviewer, issuer)}) != 3:
            raise ValueError('Three separate same-isolated-database logins required')
        self.reader, self.reviewer, self.issuer = reader, reviewer, issuer

    def identity(self, session):
        return self.reader.identity(session)

    def requests(self, session):
        return self.reader._query('SELECT retail.api_owner_portal_requests_v3(%s)', (session,), locks=True)

    def context_html(self, value):
        """Optional trusted, validated read-only context in isolated installers."""
        return ''

    def session_html(self, csrf):
        """Optional logout control for an explicitly installed auth lifecycle."""
        return ''

    @staticmethod
    def validate(value, case, request, form=None):
        if value is None:
            raise HTTPException(404, 'Review object not found')
        binding = IsolatedPortalPublicationStore.request_binding(value)
        try:
            if binding['case_id'] != case or binding['proposal_id'] != request \
                    or value['review_status'] not in STATUSES or type(value['decision_enabled']) is not bool \
                    or type(value['is_current']) is not bool:
                raise ValueError()
            observed = datetime.fromisoformat(value['observed_at'])
            created, expires = (datetime.fromisoformat(binding[name]) for name in ('created_at', 'expires_at'))
            if observed.tzinfo is None:
                raise ValueError()
            receipt = value['review_receipt']
            if value['decision'] is None:
                if receipt is not None or value['decision_id'] is not None or value['action_id'] is not None:
                    raise ValueError()
            else:
                if value['decision'] not in ('approved', 'rejected') or receipt['outcome'] != value['decision'] \
                        or receipt['request_id'] != request or receipt['request_sha256'] != value['request_sha256'] \
                        or receipt['report_sha256'] != binding['report_payload_sha256'] \
                        or receipt['reviewer_id'] != binding['reviewer_id'] or receipt['decision_id'] != value['decision_id'] \
                        or receipt['target_id'] != 'local-owner-portal-report-v2' \
                        or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', receipt['decision_key']):
                    raise ValueError()
                IsolatedPortalPublicationStore._id(receipt['decision_id'])
                decided = datetime.fromisoformat(receipt['decided_at'])
                if decided.tzinfo is None or not created <= decided < expires:
                    raise ValueError()
                if (value['decision'] == 'approved') != (value['action_id'] is not None):
                    raise ValueError()
            if value['action_id'] is not None:
                IsolatedPortalPublicationStore._id(value['action_id'])
            if value['publication'] is not None:
                IsolatedPortalPublicationStore.receipt(value, value['action_id'])
            expected = ('published' if value['publication'] is not None else
                        'rejected' if value['decision'] == 'rejected' else
                        'superseded' if not value['is_current'] else
                        ('approved_expired' if value['decision'] == 'approved' else 'expired') if observed >= expires else
                        'approved_pending_publication' if value['decision'] == 'approved' else 'pending_review')
            if value['review_status'] != expected or value['decision_enabled'] is not (expected == 'pending_review' and observed >= created):
                raise ValueError()
            report = value['report_text'].encode('utf-8')
            if len(report) != binding['action']['content_bytes'] or sha256(report).hexdigest() != binding['report_payload_sha256']:
                raise ValueError()
            if form is not None and (value['decision'] != {'approve': 'approved', 'reject': 'rejected'}[form['choice']] \
                    or receipt['decision_key'] != form['decision_key'] or value['request_sha256'] != form['proposal_sha256'] \
                    or binding['report_payload_sha256'] != form['report_sha256']):
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError, UnicodeError):
            raise HTTPException(503, 'Invalid stored review binding') from None
        return value

    def review(self, session, case, request):
        case, request = self.reader._id(case), self.reader._id(request)
        value = self.reader._query('SELECT retail.api_owner_portal_review_v3(%s,%s,%s)',
            (session, case, request), locks=True)
        return self.validate(value, case, request)

    def decide(self, session, case, request, form):
        case, request = self.reviewer._id(case), self.reviewer._id(request)
        if form['choice'] not in ('approve', 'reject'):
            raise HTTPException(422, 'Approve or reject only')
        value = self.reviewer._query('SELECT retail.api_owner_decide_portal_request_v3(%s,%s,%s,%s,%s,%s,%s,%s)',
            (session, digest(form['csrf']), case, request, form['report_sha256'], form['proposal_sha256'],
             form['choice'], form['decision_key']), True, lambda value: self.validate(value, case, request, form))
        return value

    def issue(self, case, key, payload):
        case = self.issuer._id(case)
        if not isinstance(payload, dict) or set(payload) != {'report_revision', 'report_payload_sha256', 'predecessor_request_id'} \
                or type(payload['report_revision']) is not int or payload['report_revision'] != 1 \
                or not isinstance(payload['report_payload_sha256'], str) or not HEX.fullmatch(payload['report_payload_sha256']) \
                or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', key):
            raise HTTPException(422, 'Exact issuance binding required')
        parent = payload['predecessor_request_id']
        if parent is not None:
            parent = self.issuer._id(parent)

        def validate(value):
            binding = self.issuer.request_binding(value)
            if binding['case_id'] != case or binding['report_payload_sha256'] != payload['report_payload_sha256'] \
                    or binding['request_key'] != key or binding['predecessor_proposal_id'] != parent:
                raise HTTPException(503, 'Invalid stored issuance binding')

        return self.issuer._query('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                                  (case, payload['report_payload_sha256'], key, parent), True, validate)


def _html(title, content, decisions_enabled=True, auth_page=False):
    mode = ('sign-in · decisions disabled' if auth_page else
            'owner decisions enabled' if decisions_enabled else 'read-only history · decisions disabled')
    body = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><style>body{{font:17px system-ui;background:#f5f7fa;color:#18283b;'
            'max-width:960px;margin:2rem auto;padding:0 1rem}main{background:white;padding:1.5rem;border-radius:12px}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}button{font:inherit;padding:.6rem;margin:.5rem}'
            'dt{font-weight:bold}dd{margin:0 0 .8rem;overflow-wrap:anywhere}a{color:#1748a6}</style><main>'
            f'<h1>{escape(title)}</h1><p>Isolated validation · {mode} · automatic publication disabled</p>{content}</main></html>')
    return Response(body, media_type='text/html', headers={**HEADERS, 'X-Decision-Enabled': str(decisions_enabled).lower()})


def _service_key(request):
    keys = [v for k,v in request.scope['headers'] if k.lower()==b'idempotency-key']
    try:
        if len(keys) != 1:
            raise ValueError()
        key = keys[0].decode('ascii')
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', key):
            raise ValueError()
        return key
    except (ValueError, UnicodeError):
        raise HTTPException(422, 'One exact request key required') from None


async def _service_payload(request):
    headers = request.scope['headers']
    if request.scope.get('query_string') or [v for k,v in headers if k.lower()==b'content-type'] != [b'application/json']:
        raise HTTPException(422, 'Exact JSON request required')
    key = _service_key(request)
    try:
        def unique(pairs):
            result = {}
            for name, value in pairs:
                if name in result:
                    raise ValueError()
                result[name] = value
            return result
        payload = json.loads(await request.body(), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, 'Exact JSON request required') from None
    return key, payload


def install_isolated_review_v3(app, store, portal_key, service_token, *, boundary=LEGACY_BOUNDARY,
                               demo_document_navigation=False):
    if not isinstance(store, IsolatedOwnerReview) or not HEX.fullmatch(portal_key) or not HEX.fullmatch(service_token) \
            or portal_key == service_token:
        raise ValueError('Isolated review store and separate generated keys required')
    app.add_middleware(GuardMiddleware, token=service_token)
    app.add_middleware(PortalGuard, store=store, key=portal_key, boundary=boundary,
                       demo_document_navigation=demo_document_navigation)
    _install_read_routes(app, store.reader)

    @app.exception_handler(PortalOutcomeUncertain)
    async def unknown_outcome(request, error):
        return JSONResponse({'detail': 'Outcome unavailable; inspect the request before reusing the original key'},
                            503, headers=HEADERS)

    @app.post('/api/v3/cases/{case_id}/approval-requests', include_in_schema=False)
    async def issue(case_id: str, request: Request):
        key, payload = await _service_payload(request)
        value = await run_in_threadpool(store.issue, case_id, key, payload)
        return JSONResponse(value, headers={**HEADERS, 'X-Decision-Enabled': 'false',
            'Location': f'/portal/cases/{case_id}/requests/{value["request"]["proposal_id"]}'})

    @app.get('/portal', include_in_schema=False)
    async def index(request: Request):
        rows = await run_in_threadpool(store.requests, request.state.portal_digest)
        if not isinstance(rows, list) or len(rows)>20:
            raise HTTPException(503, 'Invalid stored review binding')
        links = []
        for row in rows:
            try:
                case, identity = store.reader._id(row['case_id']), store.reader._id(row['request_id'])
                if row['review_status'] not in STATUSES:
                    raise ValueError()
                links.append(f'<li class="portal-request-card"><a class="portal-request-link" href="/portal/cases/{case}/requests/{identity}">Request {identity}</a>'
                    f'<div class="portal-request-meta"><span>{escape(row["review_status"])}</span>'
                    f'<span class="portal-generation">generation {int(row["generation"])}</span></div>'
                    f'<div class="portal-request-deadline">Original deadline: {escape(row["expires_at"])}</div></li>')
            except (KeyError, TypeError, ValueError):
                raise HTTPException(503, 'Invalid stored review binding') from None
        return _html('Portal publication requests', '<p>Latest request per case, up to 20. Viewing never renews, decides or publishes.</p>'
                     + ('<ul>'+''.join(links)+'</ul>' if links else '<p>No requests.</p>')
                     + store.session_html(request.state.portal_csrf))

    @app.get('/portal/cases/{case_id}/requests/{request_id}', include_in_schema=False)
    async def detail(case_id: str, request_id: str, request: Request):
        value = await run_in_threadpool(store.review, request.state.portal_digest, case_id, request_id)
        binding = value['request']
        if binding['reviewer_id'] != str(request.state.portal_identity):
            raise HTTPException(503, 'Invalid stored review binding')
        content = '<p><a href="/portal">All current requests</a></p><dl>'
        for label, text in (('Status', value['review_status']), ('Target', binding['action']['target']['target_id']),
                            ('Request SHA-256', value['request_sha256']), ('Report SHA-256', binding['report_payload_sha256']),
                            ('Created (UTC)', binding['created_at']), ('Original exclusive deadline (UTC)', binding['expires_at'])):
            content += f'<dt>{escape(label)}</dt><dd>{escape(text)}</dd>'
        content += '</dl><p>Approval is not publication. Server acceptance must be before this original 24-hour deadline; '
        content += 'its transaction must eventually commit and may commit after the deadline. '
        content += 'Receipt/export delivery may follow later. Viewing does not extend this clock.</p>'
        content += store.context_html(value)
        if binding['predecessor_proposal_id'] is not None:
            parent = store.reader._id(binding['predecessor_proposal_id'])
            content += f'<p><a href="/portal/cases/{case_id}/requests/{parent}">Previous request and its historical decision</a></p>'
        content += '<details><summary>Exact approval contract</summary><pre>'+escape(value['canonical_payload_text'])+'</pre></details>'
        content += '<details><summary>Stored deterministic report · not proof of publication</summary><pre>'+escape(value['report_text'])+'</pre></details>'
        if value['review_receipt'] is not None:
            content += '<h2>Stored owner decision</h2><pre>'+escape(json.dumps(value['review_receipt'], indent=2))+'</pre>'
        if value['publication'] is not None:
            action = store.reader._id(value['action_id'])
            content += '<h2>Committed publication</h2><pre>'+escape(json.dumps(value['publication'], indent=2))+'</pre>'
            content += f'<p><a href="/portal/v2/publications/{action}/export">Download exact published JSON</a></p>'
        else:
            content += '<p>Unpublished. No publication download is available.</p>'
        if value['review_status'] in ('expired', 'approved_expired'):
            content += '<p>A new explicit service request and fresh owner approval are required. No automatic renewal.</p>'
        if value['decision_enabled']:
            fields = {'csrf': request.state.portal_csrf, 'revision': '1', 'report_sha256': binding['report_payload_sha256'],
                      'proposal_sha256': value['request_sha256'], 'decision_key': 'review-v3-'+secrets.token_hex(16)}
            content += f'<form action="/portal/cases/{case_id}/requests/{request_id}/decision" method="post">'
            content += ''.join(f'<input type="hidden" name="{name}" value="{escape(text)}">' for name,text in fields.items())
            content += '<label><input type="checkbox" name="confirm" value="yes" required> '
            content += 'I confirm my selected decision for this exact request, report hash, portal target and original deadline.</label><br>'
            content += '<button name="choice" value="approve">Approve exact portal request</button>'
            content += '<button name="choice" value="reject">Reject exact portal request</button></form>'
        return _html('Portal publication review', content+store.session_html(request.state.portal_csrf))

    @app.post('/portal/cases/{case_id}/requests/{request_id}/decision', include_in_schema=False)
    async def decide(case_id: str, request_id: str, request: Request):
        await run_in_threadpool(store.decide, request.state.portal_digest, case_id, request_id, request.state.portal_form)
        return RedirectResponse(f'/portal/cases/{case_id}/requests/{request_id}', 303, headers=HEADERS)
