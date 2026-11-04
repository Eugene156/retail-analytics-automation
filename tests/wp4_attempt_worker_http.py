"""Allowlisted private attempt HTTP fixture; ONLY worker login/token are mounted."""
import json
from pathlib import Path
import re
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from api.portal_attempts import IsolatedAttemptWorker,install_isolated_attempt_worker
from api.portal_publication import IsolatedPortalPublicationStore


class Faults:
    MODES={'normal','state_retry503','lost_reserve','lost_accept','retry503','exhaust503','permanent401',
           'lost_report','lost_reconcile','interrupt_report'}
    def __init__(self,app,allowed):
        self.app,self.allowed=app,set(allowed)
        self.mode,self.action,self.calls='normal',None,[]

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        if scope['path']=='/api/__test/configure' and scope['method']=='POST':
            try:
                p=json.loads((await receive())['body'])
                if set(p)!={'mode','action_id'} or p['mode'] not in self.MODES or p['action_id'] not in self.allowed:raise ValueError()
                self.mode,self.action,self.calls=p['mode'],p['action_id'],[]
                return await JSONResponse({'configured':True})(scope,receive,send)
            except Exception:return await JSONResponse({'configured':False},400)(scope,receive,send)
        if scope['path']=='/api/__test/observations' and scope['method']=='GET':
            return await JSONResponse({'mode':self.mode,'calls':self.calls})(scope,receive,send)
        match=re.fullmatch(r'/api/v4/portal-actions/([a-f0-9-]{36})(?:/(reserve|accept|report|reconcile))?',scope['path'])
        if not match or match[1] not in self.allowed or match[1]!=self.action:
            return await JSONResponse({'detail':'Isolated allowlisted action required'},404)(scope,receive,send)
        op=match[2] or 'state'
        if scope['method']!=('GET' if op=='state' else 'POST'):
            return await JSONResponse({'detail':'Fixed operation method required'},405)(scope,receive,send)
        keys=[v for k,v in scope['headers'] if k.lower()==b'idempotency-key']
        key=keys[0].decode('ascii') if len(keys)==1 else 'invalid'
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',key):key='invalid'
        messages=[]; body=b''
        if op!='state':
            while True:
                m=await receive();messages.append(m);body+=m.get('body',b'')
                if not m.get('more_body'):break
        try:p=json.loads(body) if body else {}
        except Exception:p={}
        self.calls.append({'operation':op,'method':scope['method'],'action_id':match[1],'key':key,
                           'seconds':time.monotonic(),'execution_id':p.get('execution_id'),
                           'attempt_key':p.get('attempt_key'),'attempt_id':p.get('attempt_id'),
                           'body_bytes':len(body),'content_types':[v.decode('ascii') for k,v in scope['headers'] if k.lower()==b'content-type']})
        async def replay():return messages.pop(0) if messages else {'type':'http.request','body':b'','more_body':False}
        count=sum(c['operation']==op for c in self.calls)
        if self.mode=='state_retry503' and op=='state' and count==1:
            return await JSONResponse({'detail':'Synthetic read unavailable'},503,headers={'Retry-After':'1'})(scope,replay,send)
        if op=='accept':
            if self.mode=='permanent401':return await JSONResponse({'detail':'Synthetic permanent failure'},401)(scope,replay,send)
            if self.mode in ('exhaust503','interrupt_report') or (self.mode in ('retry503','lost_report','lost_reconcile') and count==1):
                return await JSONResponse({'detail':'Synthetic pre-write unavailable'},503,headers={'Retry-After':'1'})(scope,replay,send)
        lost={'lost_reserve':'reserve','lost_accept':'accept','lost_report':'report','lost_reconcile':'reconcile','interrupt_report':'report'}
        if lost.get(self.mode)==op and count==1:
            captured=[]
            async def collect(m):captured.append(m)
            await self.app(scope,replay,collect)
            status=next(m['status'] for m in captured if m['type']=='http.response.start')
            if status==200:
                return await JSONResponse({'detail':'Synthetic response substitution after real commit'},
                    401 if self.mode=='interrupt_report' else 503,headers={'Retry-After':'1'})(scope,replay,send)
            for m in captured:await send(m)
            return
        return await self.app(scope,replay,send)


if __name__=='__main__':
    try:
        p=json.loads(Path('/run/worker/worker.json').read_text())
        if set(p)!={'database','attempt_worker','attempt_token','allowed_actions'}:raise ValueError()
        db=p['attempt_worker']
        worker=IsolatedAttemptWorker(IsolatedPortalPublicationStore(lambda:psycopg.connect(**db),p['database'],db['user']))
        app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
        app.add_middleware(Faults,allowed=p['allowed_actions'])
        # Auth and byte cap outside controls/faults. No recovery adapter/token/routes.
        install_isolated_attempt_worker(app,worker,p['attempt_token'])
        uvicorn.run(app,host='0.0.0.0',port=8000,access_log=False,log_level='error')
    except Exception:raise SystemExit('FAIL|private-attempt-HTTP-server|details-suppressed') from None
