"""Synthetic decision UI/security checks; not human approval evidence."""
from hashlib import sha256
import copy
import json
import re
import unittest
from urllib.parse import urlencode
from uuid import UUID
from unittest.mock import patch
import psycopg
from fastapi import HTTPException
from api.main import Settings, create_app
from api.portal import PortalStore, session_csrf, validate_receipt
from api.preview import render_preview
import test_wp4_portal as portal_test
from test_wp4_portal import Store, IDENTITY, OWNER, call
from test_wp3_preview import fixture, encoded, CID

CASE=str(CID)
PROPOSAL=str(UUID(int=2020))
PATH='/portal/cases/'+CASE+'/requests/'+PROPOSAL


def receipt(report_hash,proposal_hash,outcome='approved'):
    decision={'contract_version':'local-review-decision-v1','canonicalization':'postgresql-jsonb-text-v1',
        'proposal_contract_version':'local-approval-proposal-v2','case_id':CASE,'proposal_id':PROPOSAL,
        'reviewer_id':str(IDENTITY),'report_revision':1,'report_payload_sha256':report_hash,
        'proposal_sha256':proposal_hash,'outcome':outcome,'decision_id':str(UUID(int=20))}
    canonical=json.dumps(decision)
    return {'canonical_payload_text':canonical,'decision':decision,'decision_sha256':sha256(canonical.encode()).hexdigest(),
        'published':False,'dispatch_enabled':False,'outbox':{'state':'pending','content_sha256':report_hash,
        'action_key':'publish-local-v1:'+PROPOSAL,'target_id':'local-approved-report-json-v1',
        'relative_path':'reports/approved/v1/'+CASE+'/revision-1.json'} if outcome=='approved' else None}


class DecisionStore(Store):
    decisions_enabled=True
    def __init__(self):
        super().__init__()
        self.decision_calls=[]
        self.metadata,self.payload=encoded(*fixture())
        self.report_hash=sha256(self.payload.encode()).hexdigest()
        proposal={'case_id':CASE,'proposal_id':PROPOSAL,'reviewer_id':str(IDENTITY),
                  'report_payload_sha256':self.report_hash}
        canonical=json.dumps(proposal)
        self.value={'proposal':proposal,'canonical_payload_text':canonical,'proposal_sha256':sha256(canonical.encode()).hexdigest(),
            'review_status':'pending_review','decision_enabled':True,'approved':False,'published':False,'review_receipt':None}
    def proposal(self,*args): return json.dumps(self.value)
    def decide(self,session,csrf,case,proposal,form):
        self.decision_calls.append((session,csrf,case,proposal,form.copy()))
        return json.dumps(receipt(self.report_hash,self.value['proposal_sha256'],
             {'approve':'approved','reject':'rejected','expire':'expired'}[form['choice']]))


class DecisionTests(unittest.TestCase):
    post=portal_test.PortalTests.post
    login=portal_test.PortalTests.login
    def setUp(self):
        self.store=DecisionStore()
        self.app=create_app(Settings('b'*64,'unused',portal_login_key='c'*64),portal_store=self.store)
        _,body,headers=call(self.app)
        self.csrf=re.search(rb'name="csrf" value="([a-f0-9]{64})"',body)[1].decode()
        self.challenge=next(v.decode().split(';')[0] for k,v in headers if k==b'set-cookie')
        self.cookie=self.login()
        self.raw=self.cookie.split('=')[1]
        self.headers=[(b'host',b'127.0.0.1:18081'),(b'cookie',self.cookie.encode())]
        self.form={'csrf':session_csrf(self.raw),'revision':'1','report_sha256':self.store.report_hash,
            'proposal_sha256':self.store.value['proposal_sha256'],'decision_key':'unit-decision-020','choice':'approve','confirm':'yes'}
    def decide(self,fields=None,extra=None,origin='http://127.0.0.1:18081',body=None):
        headers=self.headers+[(b'content-type',b'application/x-www-form-urlencoded')]
        if origin is not None: headers.append((b'origin',origin.encode()))
        headers.extend(extra or [])
        return call(self.app,PATH+'/decision','POST',body if body is not None else urlencode(fields or self.form).encode(),headers)

    def test_exact_binding_confirmation_csrf_and_choices(self):
        for choice in ('approve','reject','expire'):
            self.assertEqual(self.decide({**self.form,'choice':choice})[0],303)
        sent=self.store.decision_calls[0]
        self.assertEqual(sent[:4],(sha256(self.raw.encode()).hexdigest(),sha256(self.form['csrf'].encode()).hexdigest(),CID,UUID(PROPOSAL)))
        self.assertEqual(sent[4],self.form)

    def test_wrong_origin_duplicate_headers_missing_and_wrong_csrf_no_write(self):
        for origin in (None,'null','http://evil.invalid'):
            self.assertEqual(self.decide(origin=origin)[0],403)
        self.assertEqual(self.decide(extra=[(b'origin',b'http://127.0.0.1:18081')])[0],403)
        self.assertEqual(self.decide({**self.form,'csrf':'0'*64})[0],403)
        del self.form['csrf']
        self.assertEqual(self.decide()[0],400)
        self.assertFalse(self.store.decision_calls)

    def test_malformed_form_binding_unconfirmed_duplicate_and_oversize_no_write(self):
        for name,value in [('revision','true'),('choice','publish'),('decision_key','../bad'),
                           ('report_sha256','wrong'),('proposal_sha256','wrong'),('confirm','no')]:
            self.assertEqual(self.decide({**self.form,name:value})[0],422)
        self.assertEqual(self.decide(body=urlencode(self.form).encode()+b'&choice=reject')[0],400)
        self.assertEqual(self.decide(body=b'x'*2049)[0],413)
        self.assertEqual(self.decide(body=b'x=%ZZ')[0],400)
        self.assertFalse(self.store.decision_calls)

    def test_form_only_current_undecided_request(self):
        for status,enabled in [('pending_review',True),('expired',True),('superseded',False)]:
            self.store.value.update(review_status=status,decision_enabled=enabled)
            result,body,headers=call(self.app,PATH,headers=self.headers)
            self.assertEqual(result,200)
            self.assertEqual(b'value="approve"' in body,status=='pending_review')
            self.assertEqual(b'value="expire"' in body,status=='expired')
            self.assertEqual(dict(headers)[b'x-decision-enabled'],b'true')
            self.assertNotIn(self.raw.encode(),body)

    def test_receipt_tamper_is_not_success(self):
        good=receipt(self.store.report_hash,self.store.value['proposal_sha256'])
        for modify in (lambda r:r.update(decision_sha256='0'*64),lambda r:r.update(dispatch_enabled=True),
                       lambda r:r['outbox'].update(relative_path='../outside'),lambda r:r.update(outbox=None)):
            bad=copy.deepcopy(good); modify(bad)
            self.store.decide=lambda *args:json.dumps(bad)
            self.assertEqual(self.decide()[0],503)

    def test_terminal_display_and_reviewed_preview_hash_guards(self):
        good=receipt(self.store.report_hash,self.store.value['proposal_sha256'])
        self.store.value.update(review_status='approved',approved=True,decision_enabled=False,review_receipt=good)
        status,body,_=call(self.app,PATH,headers=self.headers)
        self.assertEqual(status,200); self.assertIn(b'Stored decision receipt',body)
        self.assertNotIn(b'value="approve"',body)
        metadata=json.loads(self.store.metadata)
        metadata.update(state='approved',approved=True,review_receipt=good)
        self.assertIn('APPROVED · UNPUBLISHED',render_preview(json.dumps(metadata),self.store.payload,CID))
        metadata['review_receipt']['decision_sha256']='0'*64
        with self.assertRaises(ValueError): render_preview(json.dumps(metadata),self.store.payload,CID)

    def test_commit_failure_never_returns_receipt(self):
        store=PortalStore('unused',decisions_enabled=True)
        with patch('api.portal.psycopg.connect') as connect:
            connection=connect.return_value.__enter__.return_value
            connection.execute.return_value.fetchone.side_effect=[('raa_wp4_portal_api','raa_wp2_validation'),('result',)]
            connect.return_value.__exit__.side_effect=psycopg.errors.RaiseException('deferred fault')
            with self.assertRaises(HTTPException) as error:
                store.decide('a'*64,'b'*64,CID,UUID(PROPOSAL),self.form)
            self.assertEqual(error.exception.status_code,503)

    def test_post_auth_and_service_bearer_separation(self):
        self.store.sessions.clear()
        self.assertEqual(self.decide()[0],401)
        self.assertEqual(self.decide(extra=[(b'authorization',b'Bearer '+OWNER.encode())])[0],400)
        self.assertFalse(self.store.decision_calls)
