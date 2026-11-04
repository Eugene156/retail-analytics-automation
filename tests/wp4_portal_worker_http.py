"""Private no-host-port synthetic worker/fault server; no main DB credentials."""
import hmac
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
from api.portal_publication import IsolatedPortalPublicationStore
from api.portal_worker_v2 import IsolatedPortalWorker, install_isolated_worker_v2


class Faults:
    def __init__(self,app,allowed):
        self.app,self.allowed=app,set(allowed)
        self.mode,self.action,self.calls='normal',None,[]

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        if scope['path']=='/api/__test/configure' and scope['method']=='POST':
            try:
                message=await receive(); p=json.loads(message['body'])
                if set(p)!={'mode','action_id'} or p['mode'] not in ('normal','state_retry503','retry503','lost_ack','exhaust503','permanent401') or p['action_id'] not in self.allowed:
                    raise ValueError()
                self.mode,self.action,self.calls=p['mode'],p['action_id'],[]
                return await JSONResponse({'configured':True})(scope,receive,send)
            except Exception:
                return await JSONResponse({'configured':False},400)(scope,receive,send)
        if scope['path']=='/api/__test/observations' and scope['method']=='GET':
            return await JSONResponse({'mode':self.mode,'calls':self.calls})(scope,receive,send)
        match=re.fullmatch(r'/api/v3/portal-actions/([a-f0-9-]{36})(/accept)?',scope['path'])
        if not match or match[1] not in self.allowed or match[1]!=self.action:
            return await JSONResponse({'detail':'Isolated allowlisted action required'},404)(scope,receive,send)
        keys=[v for k,v in scope['headers'] if k.lower()==b'idempotency-key']
        key=keys[0].decode('ascii') if len(keys)==1 else 'invalid'
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',key):key='invalid'
        self.calls.append({'method':scope['method'],'action_id':match[1],'key':key,'seconds':time.monotonic()})
        if self.mode=='state_retry503' and scope['method']=='GET' and len(self.calls)==1:
            return await JSONResponse({'detail':'Synthetic state read unavailable'},503,headers={'Retry-After':'1'})(scope,receive,send)
        posts=sum(c['method']=='POST' for c in self.calls)
        if scope['method']=='POST':
            if self.mode=='permanent401':
                return await JSONResponse({'detail':'Synthetic permanent failure'},401)(scope,receive,send)
            if self.mode=='exhaust503' or (self.mode=='retry503' and posts==1):
                return await JSONResponse({'detail':'Synthetic pre-write unavailable'},503,headers={'Retry-After':'1'})(scope,receive,send)
            if self.mode=='lost_ack' and posts==1:
                messages=[]
                async def collect(m):messages.append(m)
                await self.app(scope,receive,collect)
                status=next(m['status'] for m in messages if m['type']=='http.response.start')
                if status==200:
                    return await JSONResponse({'detail':'Synthetic response loss after real commit'},503,headers={'Retry-After':'1'})(scope,receive,send)
                for m in messages:await send(m)
                return
        return await self.app(scope,receive,send)


if __name__=='__main__':
    try:
        p=json.loads(Path('/run/worker/worker.json').read_text())
        if set(p)!={'database','portal_worker','worker_token','allowed_actions'}:
            raise ValueError()
        db=p['portal_worker']
        store=IsolatedPortalPublicationStore(lambda:psycopg.connect(**db),p['database'],db['user'])
        app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
        # Guard is added last and is outside fault controls too; auth/body cap first.
        app.add_middleware(Faults,allowed=p['allowed_actions'])
        install_isolated_worker_v2(app,IsolatedPortalWorker(store),p['worker_token'])
        uvicorn.run(app,host='0.0.0.0',port=8000,access_log=False,log_level='error')
    except Exception:
        raise SystemExit('FAIL|isolated-worker-server|details-suppressed') from None
