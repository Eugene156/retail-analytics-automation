"""Actual loopback form/SQL/n8n tests on fresh demo reports only, after deployment.

Uses newly generated owner credential locally, never prints it/cookies/CSRF.
No Docker configuration change, restart, removal or workflow import.
"""
from hashlib import sha256
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor
from uuid import uuid4

import p1_demo as p1
import p12_demo as setup

ORIGIN='http://127.0.0.1:18082'


class Forms(HTMLParser):
    def __init__(self):
        super().__init__(); self.fields={}; self.action=None; self.buttons=set()
    def handle_starttag(self,tag,attributes):
        a=dict(attributes)
        if tag=='form' and '/decision' in a.get('action',''):self.action=a['action']
        if tag=='input' and a.get('type')=='hidden':self.fields[a['name']]=a.get('value','')
        if tag=='button' and a.get('name')=='choice':self.buttons.add(a['value'])


def main():
    p1.guard(); c=setup.config(); db=c['database']
    client=build_opener(HTTPCookieProcessor(CookieJar()))
    def http(url,payload=None,headers=None,form=False):
        p1.require(urlsplit(url).hostname=='127.0.0.1','loopback-only-test')
        h=dict(headers or {})
        data=None
        if payload is not None:
            data=(urlencode(payload) if form else json.dumps(payload)).encode()
            h['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
        try:
            with client.open(Request(url,headers=h,data=data),timeout=45) as response:return response.status,response.read()
        except HTTPError as error:return error.code,error.read()
    def sql(text):return p1.sql('BEGIN READ ONLY; '+text+'; COMMIT;',db)
    def fresh():
        payload={'source_file_sha256':'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
         'source_time_interpretation':'Europe/London-assumed','period_start_inclusive':'2011-01-28T09:00:00Z',
         'period_end_exclusive':'2011-01-28T10:00:00Z','source_as_of_exclusive':'2011-01-28T10:00:00Z'}
        status,raw=http('http://127.0.0.1:18090/api/v1/report-requests',payload,
            {'Authorization':'Bearer '+c['primary_token'],'Idempotency-Key':'p12-tech-'+uuid4().hex})
        p1.require(status==200,'real-primary-report-ready')
        case=json.loads(raw)
        status,raw=http(ORIGIN+'/api/demo/register',{'case_id':case['case_id'],'report_sha256':case['payload_sha256']},
            {'Authorization':'Bearer '+c['service_token']})
        p1.require(status==200,'real-approval-request-issued')
        return json.loads(raw)
    status,raw=http(ORIGIN+'/portal/login'); p1.require(status==200,'real-login-page')
    form=Forms();form.feed(raw.decode())
    status,raw=http(ORIGIN+'/portal/login',{'owner_token':(setup.PRIVATE/'owner-token').read_text().strip(),
        'csrf':form.fields['csrf']},{'Origin':ORIGIN},form=True)
    p1.require(status==200,'real-owner-sign-in')
    receipts=[]
    for choice in ('approve','reject'):
        case=fresh(); req=case['request_id']
        status,raw=http(case['review_url']);p1.require(status==200,'actual-review-page')
        form=Forms();form.feed(raw.decode())
        p1.require(form.buttons=={'approve','reject'} and form.action is not None,'real-two-decision-buttons')
        # Parser also sees logout csrf (identical session binding); the decision form fields remain bound.
        fields=dict(form.fields,choice=choice,confirm='yes')
        status,_=http(ORIGIN+form.action,fields,{'Origin':'https://untrusted.invalid'},form=True)
        p1.require(status==403,'real-cross-origin-denial')
        status,raw=http(ORIGIN+form.action,fields,{'Origin':ORIGIN},form=True)
        p1.require(status==200,'real-confirmed-decision-result')
        expected='APPROVED' if choice=='approve' else 'REJECTED'
        p1.require(('<h2>'+expected+'</h2>').encode() in raw,'owner-visible-result')
        counts=sql("SELECT d.outcome,(SELECT count(*) FROM retail.portal_publications_v2 p JOIN retail.portal_publication_intents_v2 a USING(action_id) WHERE a.request_id=d.request_id) FROM retail.portal_review_decisions_v2 d WHERE d.request_id='"+req+"'")
        p1.require(counts==('approved|1' if choice=='approve' else 'rejected|0'),'real-approval-publication-invariant')
        # Replaying the same confirmed decision keeps one decision/publication.
        status,_=http(ORIGIN+form.action,fields,{'Origin':ORIGIN},form=True)
        p1.require(status==200 and sql("SELECT count(*) FROM retail.portal_review_decisions_v2 WHERE request_id='"+req+"'")=='1','real-decision-replay')
        p1.require(sql("SELECT count(*) FROM retail.portal_publications_v2 p JOIN retail.portal_publication_intents_v2 a USING(action_id) WHERE a.request_id='"+req+"'")==('1' if choice=='approve' else '0'),'no-duplicate-or-rejected-publication')
        executions=p1.sql("BEGIN READ ONLY; SELECT count(*) FROM execution_entity e JOIN execution_data d ON d.\"executionId\"=e.id WHERE e.\"workflowId\"='"+setup.DECISION+"' AND e.status='success' AND d.data LIKE '%"+req+"%'; COMMIT;",'n8n')
        p1.require(int(executions)>=2,'real-successful-n8n-decision-and-replay-executions')
        if choice=='approve':
            action=sql("SELECT action_id FROM retail.portal_publication_intents_v2 WHERE request_id='"+req+"'")
            status,export=http(ORIGIN+'/portal/v2/publications/'+action+'/export')
            p1.require(status==200 and sha256(export).hexdigest()==case['report_sha256'],'real-owner-publication-download-hash')
        receipts.append({'decision':expected,'request_id':req,'case_id':case['case_id'],
            'publication_count':1 if choice=='approve' else 0,'n8n_successful_executions':int(executions)})
        print('PASS|real-P12-'+choice+'|form-SQL-n8n|replay-safe',flush=True)
    # Save only public bindings. Check execution history before declaring safe video/demo output.
    history=p1.sql("BEGIN READ ONLY; SELECT d.data FROM execution_entity e JOIN execution_data d ON d.\"executionId\"=e.id WHERE e.\"workflowId\"='"+setup.DECISION+"'; COMMIT;",'n8n')
    protected=[c[n] for n in ('portal_key','service_token','primary_token')]+[(setup.PRIVATE/'owner-token').read_text().strip()]
    protected += [s['password'] for s in c['stores'].values()]
    p1.require(not any(v in history for v in protected),'no-secret-material-in-decision-execution-history')
    (setup.PRIVATE/'technical-verification.json').write_text(json.dumps({'status':'verified-in-current-environment',
        'checks':receipts,'owner_url':ORIGIN+'/portal','manual_report_workflow':setup.CREATE,
        'manual_new-workflow-browser-check':'not yet run','secrets_in_decision_execution_history':False},indent=2)+'\n')
    print('PASS|P12-real-Approve-Reject-download-replay-n8n|no-credential-output')


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('BLOCKED|P12-technical-check|details-suppressed|preserve-state') from None
