"""Explicit isolated attempt API surfaces. No main/n8n activation or retries."""
from datetime import datetime, timedelta
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api.main import GuardMiddleware
from api.portal import HEADERS, HEX
from api.portal_publication import PortalOutcomeUncertain
from api.portal_review_v3 import _service_key, _service_payload
from api.portal_worker_v2 import IsolatedPortalWorker


KEY = re.compile(r'[A-Za-z0-9_-]{8,128}')
EXECUTION = re.compile(r'[1-9][0-9]{0,19}')
STATES = {'pending','reserved','unknown','retryable','published','expired','superseded','dead_letter','exhausted'}
KINDS = {'reserved','accepted','reported','reconciled','operator_reconciled'}
LEDGER_FIELDS = {'state','attempt_count','max_attempts','event_no','attempt_id','attempt_key','execution_id',
                 'lease_expires_at','last_kind','reconciliation_required','acceptance_key','observed_at'}


class _AttemptBinding:
    def __init__(self, store):
        self.binding = IsolatedPortalWorker(store)  # Existing generated DB/login admission.
        self.store = store

    @staticmethod
    def key(value):
        if not isinstance(value,str) or not KEY.fullmatch(value):
            raise HTTPException(422,'Bounded original key required')
        return value

    @staticmethod
    def execution(value):
        if not isinstance(value,str) or not EXECUTION.fullmatch(value):
            raise HTTPException(422,'Exact execution identity required')
        return value

    @staticmethod
    def fields(payload, fields):
        if not isinstance(payload,dict) or set(payload)!=set(fields):
            raise HTTPException(422,'Exact attempt fields required')

    def token(self,payload):
        return self.store._id(payload['attempt_id']), self.execution(payload['execution_id'])

    def validate(self,value,action,key,expected=None,token=None):
        try:
            if not isinstance(value,dict) or set(value)!={'contract_version','worker','ledger'} \
                    or value['contract_version']!='portal-worker-attempt-state-v1':
                raise ValueError()
            worker=self.binding.validate(value['worker'],action,key,expected)
            ledger=value['ledger']
            if not isinstance(ledger,dict) or set(ledger)!=LEDGER_FIELDS:
                raise ValueError()
            n,event=ledger['attempt_count'],ledger['event_no']
            observed=datetime.fromisoformat(ledger['observed_at'])
            created,expires=(datetime.fromisoformat(worker[f]) for f in ('created_at','expires_at'))
            if observed.tzinfo is None or observed<datetime.fromisoformat(worker['observed_at']) or observed<created \
                    or type(n) is not int or not 0<=n<=3 or type(event) is not int or not n<=event<=32 \
                    or type(ledger['max_attempts']) is not int or ledger['max_attempts']!=3 \
                    or ledger['acceptance_key']!=key or ledger['state'] not in STATES:
                raise ValueError()
            state=ledger['state']; kind=ledger['last_kind']; required=ledger['reconciliation_required']
            lease=None
            if n==0:
                if event!=0 or any(ledger[f] is not None for f in ('attempt_id','attempt_key','execution_id','lease_expires_at','last_kind','reconciliation_required')):
                    raise ValueError()
                if state not in ('pending','expired','superseded','published'):
                    raise ValueError()
            else:
                self.store._id(ledger['attempt_id']); self.key(ledger['attempt_key']); self.execution(ledger['execution_id'])
                lease=datetime.fromisoformat(ledger['lease_expires_at'])
                if lease.tzinfo is None or not created<lease<=expires or lease>observed+timedelta(seconds=30) \
                        or kind not in KINDS or type(required) is not bool or state=='pending':
                    raise ValueError()
                if (kind=='reserved' and not required) or (kind in ('accepted','reconciled','operator_reconciled') and required):
                    raise ValueError()
                if state=='reserved' and (kind!='reserved' or lease<=observed):
                    raise ValueError()
                if state=='unknown' and (not required or kind not in ('reserved','reported') or (kind=='reserved' and lease>observed)):
                    raise ValueError()
                if state in ('retryable','exhausted','dead_letter') and required:
                    raise ValueError()
                if (state=='retryable' and n>=3) or (state=='exhausted' and n!=3):
                    raise ValueError()
                if kind=='accepted' and state!='published':
                    raise ValueError()
            # Ledger observation is later than the inner state clock. A request
            # may cross expiry between those samples; SQL remains authoritative.
            snapshot=value['worker']['snapshot']
            terminal='published' if worker['receipt'] is not None else 'superseded' if not snapshot['is_current'] else 'expired' if observed>=expires else None
            if (terminal is not None and state!=terminal) or (terminal is None and state in ('published','expired','superseded')):
                raise ValueError()
            if token and (ledger['attempt_id'],ledger['execution_id'])!=token:
                raise ValueError()
            worker=dict(worker,observed_at=ledger['observed_at'],status=terminal or 'pending')
            clean=dict(ledger,reconciliation_required=required is True)
            return {'contract_version':'portal-attempt-api-state-v1','worker':worker,'ledger':clean,
                    'reservation_acknowledged':False,'acceptance_permitted':False}
        except (KeyError,ValueError,TypeError,AttributeError,HTTPException):
            raise HTTPException(503,'Invalid stored attempt binding') from None

    def run(self,sql,args,action,key,write=False,check=None):
        results=[]
        def validate(value):
            results.append(check(value) if check else self.validate(value,action,key))
        self.store._query(sql,args,write=write,validate=validate,locks=True)
        # No unvalidated second query/recheck or candidate response escapes a
        # failed/unknown commit; both stores close/release on all outcomes.
        return results[0]


class IsolatedAttemptWorker(_AttemptBinding):
    def state(self,action,key):
        action=self.binding.identity(action,key)
        return self.run('SELECT retail.api_portal_attempt_state_v1(%s,%s)',(action,key),action,key)

    def reserve(self,action,key,payload):
        action=self.binding.identity(action,key)
        self.fields(payload,('case_id','request_sha256','report_sha256','attempt_key','execution_id'))
        case=self.store._id(payload['case_id']); attempt_key=self.key(payload['attempt_key']); execution=self.execution(payload['execution_id'])
        expected={f:payload[f] for f in ('case_id','request_sha256','report_sha256')}
        for field in ('request_sha256','report_sha256'):
            if not isinstance(payload[field],str) or not HEX.fullmatch(payload[field]):
                raise HTTPException(422,'Exact immutable hashes required')
        def check(value):
            result=self.validate(value,action,key,expected)
            ledger=result['ledger']
            if ledger['state']=='reserved':
                if (ledger['attempt_key'],ledger['execution_id'])!=(attempt_key,execution):
                    raise HTTPException(409,'Reservation belongs to another attempt')
                result.update(reservation_acknowledged=True,acceptance_permitted=True)
            return result
        return self.run('SELECT retail.api_reserve_portal_attempt_v1(%s,%s,%s,%s,%s,%s,%s)',
            (action,key,case,payload['request_sha256'],payload['report_sha256'],attempt_key,execution),action,key,True,check)

    def accept(self,action,key,payload):
        action=self.binding.identity(action,key); self.fields(payload,('attempt_id','execution_id')); token=self.token(payload)
        def check(value):
            result=self.validate(value,action,key,token=token)
            if result['ledger']['state']!='published' or result['worker']['receipt'] is None:
                raise HTTPException(503,'Committed publication unavailable')
            return result
        return self.run('SELECT retail.api_accept_portal_attempt_v1(%s,%s,%s,%s)',(action,key,*token),action,key,True,check)

    def report(self,action,key,payload):
        action=self.binding.identity(action,key); self.fields(payload,('attempt_id','execution_id','outcome')); token=self.token(payload)
        outcome=payload['outcome']
        if not isinstance(outcome,str) or outcome not in ('retryable','uncertain','permanent'):
            raise HTTPException(422,'Fixed outcome code required')
        allowed={'retryable':{'retryable','exhausted'},'uncertain':{'unknown'},'permanent':{'dead_letter'}}[outcome]
        def check(value):
            result=self.validate(value,action,key,token=token)
            if result['ledger']['state'] not in allowed|{'published','expired','superseded'}:
                raise HTTPException(503,'Invalid stored attempt outcome')
            return result
        return self.run('SELECT retail.api_report_portal_attempt_v1(%s,%s,%s,%s,%s)',(action,key,*token,outcome),action,key,True,check)

    def reconcile(self,action,key,payload):
        action=self.binding.identity(action,key); self.fields(payload,())
        return self.run('SELECT retail.api_reconcile_portal_attempt_v1(%s,%s)',(action,key),action,key,True)


class IsolatedAttemptRecovery(_AttemptBinding):
    def recover(self,action,key,payload):
        action=self.binding.identity(action,key); self.fields(payload,('recovery_key',))
        recovery=self.key(payload['recovery_key'])
        return self.run('SELECT retail.api_operator_reconcile_portal_v1(%s,%s,%s)',(action,key,recovery),action,key,True)


class _PrivateAttemptHeaders:
    def __init__(self,app):
        self.app=app

    async def __call__(self,scope,receive,send):
        async def private(message):
            if message['type']=='http.response.start':
                fixed={k.lower().encode():v.encode() for k,v in HEADERS.items()}
                headers=[(k,v) for k,v in message.get('headers',[]) if k.lower() not in fixed]
                message=dict(message,headers=headers+list(fixed.items()))
            await send(message)
        await self.app(scope,receive,private)


def _install_boundary(app,token):
    app.add_middleware(GuardMiddleware,token=token)
    app.add_middleware(_PrivateAttemptHeaders)

    @app.exception_handler(PortalOutcomeUncertain)
    async def unknown(request,error):
        return JSONResponse({'detail':'Attempt write outcome unknown; reconcile original action and keys before retry'},503,headers=HEADERS)

    @app.exception_handler(HTTPException)
    async def denied(request,error):
        return JSONResponse({'detail':error.detail},error.status_code,headers={**HEADERS,**(error.headers or {})})


def _service_only(request):
    if request.scope.get('query_string') or any(k.lower() in (b'cookie',b'origin') for k,v in request.scope['headers']):
        raise HTTPException(400,'Isolated service request required')


def install_isolated_attempt_surfaces(worker_app,recovery_app,worker,recovery,worker_token,recovery_token):
    if not isinstance(worker,IsolatedAttemptWorker) or not isinstance(recovery,IsolatedAttemptRecovery) \
            or worker_app is recovery_app or worker.store.database!=recovery.store.database \
            or worker.store.login==recovery.store.login or not isinstance(worker_token,str) or not HEX.fullmatch(worker_token) \
            or not isinstance(recovery_token,str) or not HEX.fullmatch(recovery_token) or worker_token==recovery_token:
        raise ValueError('Separate isolated attempt/recovery surfaces required')
    install_isolated_attempt_worker(worker_app,worker,worker_token)
    _install_boundary(recovery_app,recovery_token)

    @recovery_app.post('/api/v4/portal-actions/{action_id}/recover',include_in_schema=False)
    async def recover(action_id:str,request:Request):
        _service_only(request); key,payload=await _service_payload(request)
        return JSONResponse(await run_in_threadpool(recovery.recover,action_id,key,payload),headers=HEADERS)


def install_isolated_attempt_worker(worker_app,worker,worker_token):
    """Worker-only deployment: never needs or retains operator credentials."""
    if not isinstance(worker,IsolatedAttemptWorker) or not isinstance(worker_token,str) or not HEX.fullmatch(worker_token):
        raise ValueError('Restricted isolated attempt worker required')
    _install_boundary(worker_app,worker_token)

    @worker_app.get('/api/v4/portal-actions/{action_id}',include_in_schema=False)
    async def state(action_id:str,request:Request):
        _service_only(request)
        result=await run_in_threadpool(worker.state,action_id,_service_key(request))
        return JSONResponse(result,headers=HEADERS)

    # Explicit fixed operation/route mapping, never a caller function name.
    async def post(request,action_id,method):
        _service_only(request); key,payload=await _service_payload(request)
        return JSONResponse(await run_in_threadpool(method,action_id,key,payload),headers=HEADERS)

    @worker_app.post('/api/v4/portal-actions/{action_id}/reserve',include_in_schema=False)
    async def reserve(action_id:str,request:Request):
        return await post(request,action_id,worker.reserve)

    @worker_app.post('/api/v4/portal-actions/{action_id}/accept',include_in_schema=False)
    async def accept(action_id:str,request:Request):
        return await post(request,action_id,worker.accept)

    @worker_app.post('/api/v4/portal-actions/{action_id}/report',include_in_schema=False)
    async def report(action_id:str,request:Request):
        return await post(request,action_id,worker.report)

    @worker_app.post('/api/v4/portal-actions/{action_id}/reconcile',include_in_schema=False)
    async def reconcile(action_id:str,request:Request):
        return await post(request,action_id,worker.reconcile)
