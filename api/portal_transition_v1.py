"""Explicit isolated service transition, committed evidence and owner provenance.

Not installed by main. No login/worker/file adapter, automatic renewal or approval.
"""
from datetime import datetime, timedelta
from hashlib import sha256
from html import escape
import json
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api.portal import HEADERS, HEX, LEGACY_BOUNDARY
from api.portal_publication import IsolatedPortalPublicationStore, TARGET
from api.portal_review_v3 import IsolatedOwnerReview, _html, _service_key, _service_payload, install_isolated_review_v3

OLD_TARGET = 'local-approved-report-json-v1'
KEY = re.compile(r'[A-Za-z0-9_-]{8,128}\Z')
TRANSITION_FIELDS = {'contract_version', 'transition_id', 'case_id', 'legacy_request_id', 'legacy_request_sha256',
    'legacy_target_id', 'first_request_id', 'first_request_sha256', 'target_id', 'report_revision', 'report_sha256',
    'reviewer_id', 'request_key', 'transitioned_at', 'approval_transferred', 'legacy_files_adopted'}


class IsolatedPortalTransition(IsolatedOwnerReview):
    def __init__(self, reader, reviewer, issuer, transition):
        super().__init__(reader, reviewer, issuer)
        if not isinstance(transition, IsolatedPortalPublicationStore) or transition.database != reader.database \
                or transition.login in {reader.login, reviewer.login, issuer.login}:
            raise ValueError('Separate same-isolated-database transition login required')
        self.transition_store = transition

    @staticmethod
    def validate_transition(value, case, key=None, expected=None):
        if value is None:
            raise HTTPException(404, 'Committed transition not found')
        try:
            t, canonical = value['transition'], value['canonical_transition_text']
            if not isinstance(t, dict) or set(t) != TRANSITION_FIELDS or not isinstance(canonical, str) \
                    or len(canonical.encode('utf-8')) > 8192 or json.loads(canonical) != t \
                    or not HEX.fullmatch(value['transition_sha256']) \
                    or sha256(canonical.encode('utf-8')).hexdigest() != value['transition_sha256'] \
                    or t['case_id'] != case or t['contract_version'] != 'portal-legacy-transition-v1' \
                    or t['legacy_target_id'] != OLD_TARGET or t['target_id'] != TARGET \
                    or type(t['report_revision']) is not int or t['report_revision'] != 1 \
                    or t['approval_transferred'] is not False or t['legacy_files_adopted'] is not False \
                    or not KEY.fullmatch(t['request_key']):
                raise ValueError()
            for name in ('transition_id', 'case_id', 'legacy_request_id', 'first_request_id', 'reviewer_id'):
                IsolatedPortalPublicationStore._id(t[name])
            for name in ('legacy_request_sha256', 'first_request_sha256', 'report_sha256'):
                if not HEX.fullmatch(t[name]):
                    raise ValueError()
            first = IsolatedPortalPublicationStore.request_binding(value['new_request'])
            created = datetime.fromisoformat(first['created_at'])
            transitioned = datetime.fromisoformat(t['transitioned_at'])
            if transitioned.tzinfo is None or transitioned != created or first['case_id'] != case \
                    or first['proposal_id'] != t['first_request_id'] \
                    or value['new_request']['request_sha256'] != t['first_request_sha256'] \
                    or first['report_payload_sha256'] != t['report_sha256'] or first['reviewer_id'] != t['reviewer_id'] \
                    or type(first['generation']) is not int or first['generation'] != 1 \
                    or first['predecessor_proposal_id'] is not None or first['predecessor_proposal_sha256'] is not None \
                    or first['request_key'] != t['request_key'] or (key is not None and key != t['request_key']):
                raise ValueError()
            if expected is not None and any(t[name] != wanted for name, wanted in expected.items()):
                raise ValueError()
            snapshot = value['new_request']
            if type(snapshot['is_current']) is not bool or snapshot['dispatch_enabled'] is not False \
                    or snapshot['decision'] not in (None, 'approved', 'rejected') \
                    or (snapshot['decision'] is not None) != (snapshot['decision_id'] is not None) \
                    or (snapshot['decision'] == 'approved') != (snapshot['action_id'] is not None):
                raise ValueError()
            for name in ('decision_id', 'action_id'):
                if snapshot[name] is not None:
                    IsolatedPortalPublicationStore._id(snapshot[name])
            if snapshot['publication'] is not None:
                IsolatedPortalPublicationStore.receipt(snapshot, snapshot['action_id'])
        except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, RecursionError, HTTPException):
            raise HTTPException(503, 'Invalid stored transition binding') from None
        return value

    def transition(self, case, key, payload):
        case = self.transition_store._id(case)
        if not isinstance(payload, dict) or set(payload) != {'report_revision', 'report_payload_sha256',
                'legacy_request_id', 'legacy_request_sha256'} or type(payload['report_revision']) is not int \
                or payload['report_revision'] != 1 or not isinstance(key, str) or not KEY.fullmatch(key):
            raise HTTPException(422, 'Exact transition binding required')
        old = self.transition_store._id(payload['legacy_request_id'])
        for name in ('report_payload_sha256', 'legacy_request_sha256'):
            if not isinstance(payload[name], str) or not HEX.fullmatch(payload[name]):
                raise HTTPException(422, 'Exact transition binding required')
        expected = {'legacy_request_id': old, 'legacy_request_sha256': payload['legacy_request_sha256'],
                    'report_sha256': payload['report_payload_sha256']}
        return self.transition_store._query('SELECT retail.api_transition_legacy_portal_v1(%s,%s,%s,%s,%s)',
            (case, old, payload['legacy_request_sha256'], payload['report_payload_sha256'], key), True,
            lambda value: self.validate_transition(value, case, key, expected))

    def state(self, case, key):
        case = self.transition_store._id(case)
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise HTTPException(422, 'Original transition key required')
        return self.transition_store._query('SELECT retail.api_portal_transition_state_v1(%s,%s)',
            (case, key), validate=lambda value: self.validate_transition(value, case, key), locks=True)

    def provenance(self, session, case, identity=None):
        case = self.reader._id(case)
        value = self.reader._query('SELECT retail.api_owner_portal_transition_v1(%s,%s)',
            (self.reader._session(session), case), locks=True)
        if value is None:
            return None
        self.validate_transition(value, case)
        if identity is not None and value['transition']['reviewer_id'] != identity:
            raise HTTPException(503, 'Invalid stored transition binding')
        return value

    def review(self, session, case, request):
        value = super().review(session, case, request)
        provenance = self.provenance(session, case, value['request']['reviewer_id'])
        if provenance is not None:
            t, r = provenance['transition'], value['request']
            if t['report_sha256'] != r['report_payload_sha256'] \
                    or (r['generation'] == 1 and (r['proposal_id'] != t['first_request_id'] \
                        or value['request_sha256'] != t['first_request_sha256'])):
                raise HTTPException(503, 'Invalid stored transition binding')
        value['legacy_transition'] = provenance
        return value

    def context_html(self, value):
        evidence = value.get('legacy_transition')
        return _provenance_html(evidence) if evidence is not None else ''

    @staticmethod
    def validate_legacy(value, case, old):
        IsolatedPortalTransition.validate_transition(value, case)
        try:
            t, saved = value['transition'], value['legacy_request']
            r, canonical = saved['request'], saved['canonical_payload_text']
            event = saved['creation_event']
            created, expires = (datetime.fromisoformat(r[name]) for name in ('created_at', 'expires_at'))
            retired = datetime.fromisoformat(t['transitioned_at'])
            if value['legacy_status'] != 'retired' or value['decision_enabled'] is not False \
                    or value['legacy_published'] is not False or json.loads(canonical) != r \
                    or len(canonical.encode('utf-8')) > 32768 \
                    or not HEX.fullmatch(saved['request_sha256']) \
                    or sha256(canonical.encode('utf-8')).hexdigest() != saved['request_sha256'] \
                    or r['proposal_id'] != old or r['case_id'] != case or r['reviewer_id'] != t['reviewer_id'] \
                    or r['contract_version'] != 'local-approval-proposal-v2' or r['review_policy_version'] != 'local-publication-v1' \
                    or r['canonicalization'] != 'postgresql-jsonb-text-v1' \
                    or r['report_schema_version'] != 'deterministic-comparison-report-v1' \
                    or type(r['generation']) is not int or r['generation'] < 1 or not KEY.fullmatch(r['request_key']) \
                    or type(r['report_revision']) is not int or r['report_revision'] != 1 \
                    or r['report_payload_sha256'] != t['report_sha256'] or r['action']['content_sha256'] != t['report_sha256'] \
                    or r['action']['type'] != 'publish_local_report_json_v1' \
                    or type(r['action']['content_bytes']) is not int \
                    or r['action']['content_bytes'] != value['new_request']['request']['action']['content_bytes'] \
                    or r['action']['target'] != {'target_id':OLD_TARGET, 'media_type':'application/json',
                        'relative_path':'reports/approved/v1/'+case+'/revision-1.json'} \
                    or created.tzinfo is None or expires.tzinfo is None or expires-created != timedelta(seconds=86400) \
                    or expires > retired or event['event_type'] != 'approval_request_created' \
                    or event['actor'] != 'local-service-v1' or datetime.fromisoformat(event['occurred_at']) != created \
                    or (old == t['legacy_request_id'] and saved['request_sha256'] != t['legacy_request_sha256']):
                raise ValueError()
            IsolatedPortalPublicationStore._id(event['event_id'])
        except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, RecursionError, HTTPException):
            raise HTTPException(503, 'Invalid stored legacy history') from None
        return value

    def legacy(self, session, case, old):
        case, old = self.reader._id(case), self.reader._id(old)
        return self.reader._query('SELECT retail.api_owner_retired_legacy_request_v1(%s,%s,%s)',
            (self.reader._session(session), case, old), validate=lambda value: self.validate_legacy(value, case, old), locks=True)


def _provenance_html(value):
    t = value['transition']
    case, old, first = t['case_id'], t['legacy_request_id'], t['first_request_id']
    content = '<section><h2>Legacy target retired · fresh approval required</h2>'
    content += '<p>No legacy approval was transferred and no legacy file was adopted. '
    content += 'This separate transition record binds the unchanged old request to the first new portal request.</p><dl>'
    for label, text in (('Transition SHA-256', value['transition_sha256']), ('Retired target', t['legacy_target_id']),
                        ('Legacy request SHA-256', t['legacy_request_sha256']), ('First portal request SHA-256', t['first_request_sha256']),
                        ('Transition time (UTC)', t['transitioned_at'])):
        content += f'<dt>{escape(label)}</dt><dd>{escape(text)}</dd>'
    content += f'</dl><p><a href="/portal/legacy/cases/{case}/requests/{old}">Unchanged retired legacy request</a> · '
    content += f'<a href="/portal/cases/{case}/requests/{first}">First portal request and its own decision</a></p>'
    content += '<details><summary>Exact separate transition evidence</summary><pre>'
    content += escape(value['canonical_transition_text'])+'</pre></details></section>'
    return content


def install_isolated_transition_v1(app, store, portal_key, service_token, *, boundary=LEGACY_BOUNDARY):
    if not isinstance(store, IsolatedPortalTransition):
        raise ValueError('Isolated transition store required')
    install_isolated_review_v3(app, store, portal_key, service_token, boundary=boundary)

    def service_only(request):
        if request.scope.get('query_string'):
            raise HTTPException(422, 'No transition query parameters')
        if any(k.lower() in (b'cookie', b'origin') for k,v in request.scope['headers']):
            raise HTTPException(400, 'Service request required')

    @app.post('/api/v3/cases/{case_id}/portal-transition', include_in_schema=False)
    async def transition(case_id: str, request: Request):
        service_only(request)
        key, payload = await _service_payload(request)
        value = await run_in_threadpool(store.transition, case_id, key, payload)
        first = value['transition']['first_request_id']
        return JSONResponse(value, headers={**HEADERS, 'Location':f'/portal/cases/{case_id}/requests/{first}'})

    @app.get('/api/v3/cases/{case_id}/portal-transition', include_in_schema=False)
    async def state(case_id: str, request: Request):
        service_only(request)
        value = await run_in_threadpool(store.state, case_id, _service_key(request))
        return JSONResponse(value, headers=HEADERS)

    @app.get('/portal/cases/{case_id}/transition', include_in_schema=False)
    async def evidence(case_id: str, request: Request):
        value = await run_in_threadpool(store.provenance, request.state.portal_digest, case_id, str(request.state.portal_identity))
        if value is None:
            raise HTTPException(404, 'Committed transition not found')
        return _html('Committed target transition', '<p><a href="/portal">All current requests</a></p>'+_provenance_html(value)
                     +store.session_html(request.state.portal_csrf), False)

    @app.get('/portal/legacy/cases/{case_id}/requests/{request_id}', include_in_schema=False)
    async def legacy(case_id: str, request_id: str, request: Request):
        value = await run_in_threadpool(store.legacy, request.state.portal_digest, case_id, request_id)
        if value['transition']['reviewer_id'] != str(request.state.portal_identity):
            raise HTTPException(503, 'Invalid stored legacy history')
        content = '<p>Retired legacy request · read-only history. No decision, renewal or publication controls.</p>'
        content += _provenance_html(value)
        content += '<h2>Unchanged legacy approval contract</h2><pre>'+escape(value['legacy_request']['canonical_payload_text'])+'</pre>'
        return _html('Retired legacy request', content+store.session_html(request.state.portal_csrf), False)
