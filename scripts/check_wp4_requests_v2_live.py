"""Actual loopback issuance/replay checks for one retained, UNAPPROVED M02 case.

Ten initial concurrent calls use one fixed key. Replays never renew it. This
does not wait 24 hours, forge a human decision, or publish any artifact.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
import json
import secrets
import time

from wp4_reviewer_local import CASE, SECRET_DIR, credentials, http

KEY='wp4-m02-approval-request-v2-01'
PATH='/api/v2/cases/'+CASE+'/approval-requests'


class CheckFailure(Exception):
    """Only predefined safe labels enter this exception."""


def expect(condition,label):
    if not condition: raise CheckFailure(label)


def main():
    owner=credentials()
    service=(SECRET_DIR/'token').read_text(encoding='utf-8').strip()
    before=http('/api/v1/cases/'+CASE,service)
    report_before=http('/api/v1/cases/'+CASE+'/revisions/1',service)
    expect(before[0]==report_before[0]==200,'retained-case-required')
    metadata=json.loads(before[1])
    report_hash=sha256(report_before[1]).hexdigest()
    expect(metadata['payload_sha256']==report_hash and not metadata['approved'] and not metadata['published'],'exact-unapproved-report')
    body={'report_revision':1,'report_payload_sha256':report_hash,'predecessor_proposal_id':None}
    for token in (None,'wrong',owner['token']):
        expect(http(PATH,token,'POST',{'Idempotency-Key':KEY},body)[0]==401,'service-only-issuance')
    for bad in ({**body,'reviewer_id':'caller-value'},{**body,'ttl_seconds':60},
                {**body,'report_revision':True},{k:v for k,v in body.items() if k!='predecessor_proposal_id'}):
        expect(http(PATH,service,'POST',{'Idempotency-Key':KEY},bad)[0]==422,'strict-issuance-body')
    expect(http(PATH,service,'POST',body=body)[0]==422,'required-request-key')

    def submit(index):
        for attempt in range(3):
            status,data,headers=http(PATH,service,'POST',{'Idempotency-Key':KEY},body)
            if status==200:
                expect(headers.get('Cache-Control')=='no-store' and headers.get('X-Decision-Enabled')=='false','private-disabled-response')
                return json.loads(data)
            expect(status==429 and attempt<2,'bounded-concurrent-http-'+str(status)+'-attempt-'+str(attempt+1))
            delay=headers.get('Retry-After')
            expect(delay=='5','bounded-database-busy-delay')
            # Honor the minimum without synchronizing ten callers into another
            # burst. Initial calls remain concurrent; max three attempts.
            time.sleep(5+index*0.2+secrets.randbelow(1000)/1000)
        raise CheckFailure('retry-limit')

    with ThreadPoolExecutor(max_workers=10) as pool:
        results=list(pool.map(submit,range(10)))
    first=results[0]
    proposal=first['proposal']
    identifier=proposal['proposal_id']
    immutable=first['canonical_payload_text']
    digest=first['proposal_sha256']
    expect(sha256(immutable.encode('utf-8')).hexdigest()==digest,'canonical-text-hash')
    expect(all(r['canonical_payload_text']==immutable and r['proposal_sha256']==digest
               and r['creation_event']==first['creation_event'] for r in results),'concurrent-single-request-and-event')
    expect(proposal['contract_version']=='local-approval-proposal-v2' and proposal['request_key']==KEY
        and proposal['generation']==1 and proposal['predecessor_proposal_id'] is None
        and proposal['predecessor_proposal_sha256'] is None and proposal['reviewer_id']==owner['reviewer_id']
        and proposal['report_payload_sha256']==report_hash,'server-bound-identity')
    created=datetime.fromisoformat(proposal['created_at'].replace('Z','+00:00'))
    expires=datetime.fromisoformat(proposal['expires_at'].replace('Z','+00:00'))
    expect((expires-created).total_seconds()==86400,'elapsed-24-hours')
    expect(not first['decision_enabled'] and not first['approved'] and not first['published'],'no-decision-publication')
    for path,token in ((PATH+'/current',service),(PATH+'/'+identifier,service),
                       ('/review/v2/cases/'+CASE+'/approval-requests/current',owner['token']),
                       ('/review/v2/cases/'+CASE+'/approval-requests/'+identifier,owner['token'])):
        status,data,_=http(path,token)
        expect(status==200 and json.loads(data)['canonical_payload_text']==immutable,'service-owner-projections')
    expect(http('/review/v2/cases/'+CASE+'/approval-requests/current',service)[0]==401,'owner-only-read')
    expect(http('/review/v2/cases/'+CASE+'/approval-requests/'+identifier,owner['token'],'POST',body=body)[0]==405,'owner-remains-read-only')
    expect(http('/api/v1/cases/'+CASE+'/approval-proposal',service,'POST',body=body)[0]==410,'legacy-issuance-retired')
    expect(http(PATH,service,'POST',{'Idempotency-Key':KEY},{**body,'predecessor_proposal_id':identifier})[0]==409,'same-key-changed-predecessor')
    expect(http(PATH,service,'POST',{'Idempotency-Key':KEY},{**body,'report_payload_sha256':'0'*64})[0]==409,'report-hash-conflict')
    if datetime.now(created.tzinfo)<expires:
        expect(http(PATH,service,'POST',{'Idempotency-Key':'wp4-m02-early-renewal-v2'},
                    {**body,'predecessor_proposal_id':identifier})[0]==409,'no-early-renewal')
    expect(http('/api/v2/cases/'+CASE+'/decision',service,'POST',body={'decision':'approve'})[0]==404,'no-decision-route')
    expect(http('/api/v1/cases/'+CASE,service)[1]==before[1]
           and http('/api/v1/cases/'+CASE+'/revisions/1',service)[1]==report_before[1],'unchanged-case-and-report')
    print('PASS|actual-http-v2|ten-concurrent-same-key|one-identity-event|owner-read|hash-key-predecessor-guards|no-decision|unchanged-report')
    print('REQUEST|'+identifier+'|'+digest+'|'+proposal['created_at']+'|'+proposal['expires_at'])


if __name__=='__main__':
    try: main()
    except CheckFailure as error:
        raise SystemExit('FAIL|actual-http-v2|'+str(error)) from None
    except Exception:
        raise SystemExit('FAIL|actual-http-v2|private-diagnostics-suppressed') from None
