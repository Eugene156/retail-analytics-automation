"""Real process exits/held commit points, private worker-only synthetic listener."""
import json
import os
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


class Controls:
    MODES={'normal','exit_before_accept_commit','exit_after_accept_commit','hold_after_reserve_commit','hold_before_accept_commit'}
    def __init__(self):self.mode='normal';self.action=None


class PointConnection:
    def __init__(self,conn,controls):self.conn,self.controls,self.point=conn,controls,None
    def __getattr__(self,name):return getattr(self.conn,name)
    @property
    def read_only(self):return self.conn.read_only
    @read_only.setter
    def read_only(self,value):self.conn.read_only=value
    def execute(self,sql,args=None):
        value=self.conn.execute(sql,args)
        op='accept' if sql.startswith('SELECT retail.api_accept_portal_attempt_v1(') else 'reserve' if sql.startswith('SELECT retail.api_reserve_portal_attempt_v1(') else None
        if op and args and args[0]==self.controls.action:self.point=(op,args)
        return value
    def marker(self,mode,args):
        execution=args[-1]
        if not isinstance(execution,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',execution):raise ValueError()
        print('TESTPOINT|'+mode+'|'+execution,flush=True)
    def commit(self):
        mode=self.controls.mode
        op,args=self.point or (None,None)
        if op=='accept' and mode in ('exit_before_accept_commit','hold_before_accept_commit'):
            self.marker(mode,args)
            if mode=='exit_before_accept_commit':os._exit(23)
            while True:time.sleep(.25)  # Owned test process is killed by the drill.
        result=self.conn.commit()
        if op=='accept' and mode=='exit_after_accept_commit':self.marker(mode,args);os._exit(24)
        if op=='reserve' and mode=='hold_after_reserve_commit':
            self.marker(mode,args)
            while True:time.sleep(.25)
        return result


class Boundary:
    def __init__(self,app,allowed,controls):self.app,self.allowed,self.controls=app,set(allowed),controls
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        if scope['path']=='/api/__test/configure' and scope['method']=='POST':
            try:
                p=json.loads((await receive())['body'])
                if set(p)!={'mode','action_id'} or p['mode'] not in Controls.MODES or p['action_id'] not in self.allowed:raise ValueError()
                self.controls.mode,self.controls.action=p['mode'],p['action_id']
                return await JSONResponse({'configured':True})(scope,receive,send)
            except Exception:return await JSONResponse({'configured':False},400)(scope,receive,send)
        if scope['path']=='/api/__test/ready' and scope['method']=='GET':
            return await JSONResponse({'ready':True})(scope,receive,send)
        match=re.fullmatch(r'/api/v4/portal-actions/([a-f0-9-]{36})(?:/(reserve|accept|report|reconcile))?',scope['path'])
        if not match or match[1] not in self.allowed:return await JSONResponse({'detail':'Isolated allowlisted action required'},404)(scope,receive,send)
        return await self.app(scope,receive,send)


if __name__=='__main__':
    try:
        p=json.loads(Path('/run/worker/worker.json').read_text())
        if set(p)!={'database','attempt_worker','attempt_token','allowed_actions'}:raise ValueError()
        controls=Controls();db=p['attempt_worker']
        worker=IsolatedAttemptWorker(IsolatedPortalPublicationStore(lambda:PointConnection(psycopg.connect(**db),controls),p['database'],db['user']))
        app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
        app.add_middleware(Boundary,allowed=p['allowed_actions'],controls=controls)
        install_isolated_attempt_worker(app,worker,p['attempt_token'])
        uvicorn.run(app,host='0.0.0.0',port=8000,access_log=False,log_level='error')
    except Exception:raise SystemExit('FAIL|isolated-recovery-worker|details-suppressed') from None
