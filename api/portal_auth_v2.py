"""Explicit isolated new-target authentication. No main import or activation."""
from datetime import datetime, timedelta
from html import escape
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from api.portal import HEADERS, LEGACY_BOUNDARY, _install_auth_routes
from api.portal_publication import IsolatedPortalPublicationStore, PortalOutcomeUncertain
from api.portal_review_v3 import _html
from api.portal_transition_v1 import IsolatedPortalTransition, install_isolated_transition_v1


class AuthOutcomeUncertain(RuntimeError):
    """No successful cookie/redirect until auth commit is acknowledged."""


class IsolatedPortalAuth(IsolatedPortalTransition):
    def __init__(self, reader, reviewer, issuer, transition, auth):
        super().__init__(reader, reviewer, issuer, transition)
        if not isinstance(auth, IsolatedPortalPublicationStore) or auth.database != reader.database \
                or auth.login in {reader.login, reviewer.login, issuer.login, transition.login}:
            raise ValueError('Separate same-isolated-database auth login required')
        self.auth = auth

    def identity(self, session):
        def validate(value):
            if not isinstance(value, UUID):
                raise HTTPException(401, 'Unauthorized')
        return self.auth._query('SELECT retail.api_portal_auth_identity_v2(%s)',
            (self.auth._session(session),), validate=validate, locks=True)

    def login(self, owner, session, csrf, old):
        for value in (owner, session, csrf):
            self.auth._session(value)
        if old is not None:
            self.auth._session(old)

        def validate(value):
            try:
                if not isinstance(value, dict) or set(value) != {'reviewer_id', 'created_at', 'expires_at'}:
                    raise ValueError()
                self.auth._id(value['reviewer_id'])
                created, expires = (datetime.fromisoformat(value[name]) for name in ('created_at', 'expires_at'))
                if created.tzinfo is None or expires.tzinfo is None or expires-created != timedelta(seconds=3600):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, HTTPException):
                raise HTTPException(503, 'Invalid stored session binding') from None
        try:
            return self.auth._query('SELECT retail.api_portal_auth_login_v2(%s,%s,%s,%s)',
                                    (owner, session, csrf, old), True, validate)
        except PortalOutcomeUncertain:
            raise AuthOutcomeUncertain() from None

    def logout(self, session, csrf):
        def validate(value):
            if value is not True:
                raise HTTPException(503, 'Invalid stored logout binding')
        try:
            return self.auth._query('SELECT retail.api_portal_auth_logout_v2(%s,%s)',
                (self.auth._session(session), self.auth._session(csrf)), True, validate)
        except PortalOutcomeUncertain:
            raise AuthOutcomeUncertain() from None

    def session_html(self, csrf):
        self.auth._session(csrf)
        return ('<form action="/portal/logout" method="post">'
                f'<input type="hidden" name="csrf" value="{escape(csrf)}"><button>Sign out</button></form>')


def install_isolated_auth_v2(app, store, portal_key, service_token, *, boundary=LEGACY_BOUNDARY):
    if not isinstance(store, IsolatedPortalAuth):
        raise ValueError('Isolated auth store required')
    install_isolated_transition_v1(app, store, portal_key, service_token, boundary=boundary)
    notice = ('<p>Synthetic UAT only. Historical report fixtures, not the real M02 case. '
              'No automatic approval, renewal or publication.</p>') if boundary.profile == 'isolated-uat' else ''
    _install_auth_routes(app, store, portal_key, lambda title, content: _html(title, notice+content, False, auth_page=True), boundary)

    @app.exception_handler(AuthOutcomeUncertain)
    async def unknown_auth(request, error):
        return JSONResponse({'detail': 'Authentication outcome unavailable; reload sign-in. No new session cookie was issued'},
                            503, headers=HEADERS)
