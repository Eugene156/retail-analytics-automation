"""V2 ASGI/model/fixed-query tests; no real approval is simulated."""
from hashlib import sha256
import json
import secrets
import threading
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException
from api.main import ApprovalRequestV2, CaseStore, Settings, create_app
from api.reviewer import ReviewerStore
from test_wp2_api import FakeCalculator, call
from test_wp4_reviewer import FakeReviewer

CID=UUID(int=17)
PID=UUID(int=18)
HASH='a'*64
BODY={'report_revision':1,'report_payload_sha256':HASH,'predecessor_proposal_id':None}
TEXT=json.dumps({'proposal':{'proposal_id':str(PID)},'decision_enabled':False,'approved':False,'published':False})


class FakeStore:
    def __init__(self): self.calls=[]
    def issue_approval_request(self,cid,key,payload):
        self.calls.append(('issue',cid,key,payload.predecessor_proposal_id))
        return TEXT
    def approval_request(self,cid,pid=None):
        self.calls.append(('get',cid,pid))
        return TEXT


class FakeOwner(FakeReviewer):
    def approval_request(self,digest,cid,pid=None):
        self.calls.append(('request',digest,cid,pid))
        return TEXT


class Routes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service,self.owner=secrets.token_hex(32),secrets.token_hex(32)
        self.store,self.reader=FakeStore(),FakeOwner(self.owner)
        self.app=create_app(Settings(self.service,'unused'),FakeCalculator(),self.store,self.reader)
        self.path=f'/api/v2/cases/{CID}/approval-requests'

    async def post(self,body=BODY,key='v2-unit-fixture',headers=None,token=None):
        extra=[] if key is None else [(b'idempotency-key',key.encode())]
        return await call(self.app,'POST',self.path,json.dumps(body).encode(),
                          self.service if token is None else token,extra_headers=extra+(headers or []))

    async def test_auth_before_parse_owner_service_separation(self):
        for token in (None,'wrong',self.owner):
            self.assertEqual((await call(self.app,'POST',self.path,b'{broken',token))[0],401)
        self.assertEqual((await call(self.app,'POST',self.path,json.dumps(BODY).encode(),self.service,True))[0],401)
        self.assertEqual(self.store.calls,[])
        self.assertEqual((await call(self.app,'GET',f'/review/v2/cases/{CID}/approval-requests/current',token=self.service))[0],401)

    async def test_strict_predecessor_revision_hash_and_forbidden_fields(self):
        bad=[{k:v for k,v in BODY.items() if k!='predecessor_proposal_id'},
             *({**BODY,'predecessor_proposal_id':v} for v in (True,1,[],{},str(UUID(int=0)),str(PID).replace('-',''),'bad')),
             *({**BODY,'report_revision':v} for v in (True,1.0,'1',2)),
             {**BODY,'report_payload_sha256':HASH.upper()},
             *({**BODY,k:'private-value'} for k in ('reviewer_id','target','ttl_seconds','expires_at','approved','generation'))]
        for body in bad:
            status,response,_=await self.post(body)
            self.assertEqual(status,422)
            self.assertNotIn(b'private-value',response)
        self.assertEqual(self.store.calls,[])

    async def test_single_bounded_key_required(self):
        for key in (None,'tiny','x'*129,'spaces not allowed','Юникод1234'):
            self.assertEqual((await self.post(key=key))[0],422)
        self.assertEqual((await self.post(headers=[(b'idempotency-key',b'other-key')]))[0],422)
        self.assertEqual(self.store.calls,[])

    async def test_exact_bytes_location_and_explicit_successor(self):
        for body in (BODY,{**BODY,'predecessor_proposal_id':str(PID)}):
            status,response,headers=await self.post(body)
            self.assertEqual((status,response),(200,TEXT.encode()))
            self.assertIn((b'location',(self.path+'/'+str(PID)).encode()),headers)
            self.assertIn((b'cache-control',b'no-store'),headers)
            self.assertIn((b'x-decision-enabled',b'false'),headers)
        self.assertEqual(self.store.calls[-1],('issue',CID,'v2-unit-fixture',PID))

    async def test_read_current_history_owner_digest_and_no_decision(self):
        for suffix in ('current',str(PID)):
            self.assertEqual((await call(self.app,'GET',self.path+'/'+suffix,token=self.service))[1],TEXT.encode())
            path=f'/review/v2/cases/{CID}/approval-requests/'+suffix
            self.assertEqual((await call(self.app,'GET',path,token=self.owner))[1],TEXT.encode())
            self.assertEqual(self.reader.calls[-1][1],sha256(self.owner.encode()).hexdigest())
            self.assertEqual((await call(self.app,'POST',path,token=self.owner))[0],405)
        self.assertEqual((await call(self.app,'POST',f'/api/v2/cases/{CID}/decision',token=self.service))[0],404)
        self.assertEqual((await call(self.app,'POST',f'/api/v1/cases/{CID}/approval-proposal',token=self.service))[0],410)

    async def test_safe_failure_and_openapi(self):
        for code in (404,409,429,503):
            with patch.object(self.store,'issue_approval_request',side_effect=HTTPException(code,'Safe failure')):
                self.assertEqual((await self.post())[0],code)
        schema=json.loads((await call(self.app,'GET','/openapi.json',token=self.service))[1])
        route=schema['paths']['/api/v2/cases/{case_id}/approval-requests']['post']
        self.assertEqual(route['security'],[{'CalculationToken':[]}])
        self.assertTrue(route['parameters'][-1]['required'])
        for path,methods in schema['paths'].items():
            if path.startswith('/review/v2/'):
                self.assertEqual(methods['get']['security'],[{'OwnerReadToken':[]}])


class Adapters(unittest.TestCase):
    def test_admission_busy_before_connect_and_release_after_failure(self):
        store=CaseStore(Settings(secrets.token_hex(32),'unused','unused'),threading.BoundedSemaphore(1))
        store.approval_slot.acquire()
        try:
            with patch.object(store,'query') as query,self.assertRaises(HTTPException) as error:
                store.issue_approval_request(CID,'fixture-v2',ApprovalRequestV2(**BODY))
            self.assertEqual(error.exception.status_code,429)
            self.assertEqual(error.exception.headers,{'Retry-After':'5'})
            query.assert_not_called()
        finally: store.approval_slot.release()
        with patch.object(store,'query',side_effect=HTTPException(503,'Safe failure')),self.assertRaises(HTTPException):
            store.issue_approval_request(CID,'fixture-v2',ApprovalRequestV2(**BODY))
        self.assertTrue(store.approval_slot.acquire(blocking=False))
        store.approval_slot.release()

    def test_fixed_issuance_and_read_queries_no_reserialization(self):
        store=CaseStore(Settings(secrets.token_hex(32),'unused','unused'),threading.BoundedSemaphore(1))
        with patch.object(store,'query',return_value=TEXT) as query:
            self.assertEqual(store.issue_approval_request(CID,'fixture-v2',ApprovalRequestV2(**BODY)),TEXT)
            query.assert_called_once_with('SELECT retail.api_issue_approval_request_v2(%s, %s, %s, %s, %s)',(CID,1,HASH,'fixture-v2',None))
        with patch.object(store,'query',return_value=TEXT) as query:
            self.assertEqual(store.approval_request(CID,PID),TEXT)
            query.assert_called_once_with('SELECT retail.api_get_approval_request_v2(%s, %s)',(CID,PID),read_only=True)
        with patch.object(store,'query',return_value=TEXT) as query:
            self.assertEqual(store.approval_request(CID),TEXT)
            query.assert_called_once_with('SELECT retail.api_current_approval_request_v2(%s)',(CID,),read_only=True)

    def test_owner_fixed_queries_and_absent_result(self):
        store=ReviewerStore('unused')
        with patch.object(store,'query',return_value=TEXT) as query:
            self.assertEqual(store.approval_request('digest',CID,PID),TEXT)
            query.assert_called_once_with('SELECT retail.api_owner_approval_request_v2(%s,%s,%s)',('digest',CID,PID))
        with patch.object(store,'query',return_value=None),self.assertRaises(HTTPException) as error:
            store.approval_request('digest',CID)
        self.assertEqual(error.exception.status_code,404)


if __name__=='__main__': unittest.main()
