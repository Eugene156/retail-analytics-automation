"""Prepare/provision/install only P1.2 in the existing raa-p1-demo cluster.

prepare is offline. provision/install require separate explicit Docker approval.
Never uses historical helpers/credentials/dumps or removes Docker resources.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import secrets
from uuid import uuid4

import p1_demo as p1

ROOT=p1.ROOT
PRIVATE=p1.PRIVATE/'approval'
CREATE='p12-create-report-v1'
DECISION='p12-human-decision-v1'
N8N='raa-p1-demo-n8n-1'

FUNCTIONS={
 'reader':('api_portal_identity_v1(text)','api_owner_portal_request_v3(text,uuid)',
   'api_owner_portal_receipt_v2(text,uuid)','api_owner_portal_export_v2(text,uuid)',
   'api_owner_portal_review_v3(text,uuid,uuid)','api_owner_portal_requests_v3(text)',
   'api_owner_portal_transition_v1(text,uuid)'),
 'reviewer':('api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text)',),
 'issuer':('api_issue_portal_request_v3(uuid,text,text,uuid)',),
 'transition':(),
 'auth':('api_portal_auth_identity_v2(text)','api_portal_auth_login_v2(text,text,text,text)',
         'api_portal_auth_logout_v2(text,text)'),
 'worker':('api_worker_portal_state_v2(uuid,text)','api_worker_accept_portal_v2(uuid,text,uuid,text,text)'),
 'registry':('p12_register_report(uuid,jsonb,text,text)',),
 'state':('p12_decision_state(uuid)',),
}


def workflow_sources():
    create=p1.workflow(); create['id']=CREATE; create['name']='P1.2 Create Report for Human Approval'
    for n in create['nodes']:
        if n['name']=='Prepare request':
            source=n['parameters']['jsCode']
            p1.require(source.count("'wp3-manual-m02-v1'")==1,'original-idempotency-binding')
            n['parameters']['jsCode']=source.replace("'wp3-manual-m02-v1'","('p12-report-' + $execution.id)")
    create['nodes'].append({'id':'p12-register','name':'Open Human Approval request','type':'n8n-nodes-base.httpRequest',
      'typeVersion':4.2,'position':[2420,0],'parameters':{'method':'POST','url':'http://approval:8000/api/demo/register',
       'authentication':'genericCredentialType','genericAuthType':'httpHeaderAuth','sendBody':True,'specifyBody':'json',
       'jsonBody':"={{ JSON.stringify({case_id:$json.case_id,report_sha256:$json.payload_sha256}) }}",'options':{'timeout':35000}}})
    create['connections']['Verified unapproved draft']={'main':[[{'node':'Open Human Approval request','type':'main','index':0}]]}
    decision={'id':DECISION,'name':'P1.2 Human Decision and Local Publication','active':False,
     'nodes':[
      {'id':'p12-hook','name':'Committed Human Decision','type':'n8n-nodes-base.webhook','typeVersion':2,
       'position':[0,0],'webhookId':str(uuid4()),'parameters':{'httpMethod':'POST','path':'p12-decision',
        'authentication':'none','responseMode':'lastNode','options':{'ipWhitelist':'__DEMO_APPROVAL_IPS__'}}},
      {'id':'p12-advance','name':'Publish only approved report','type':'n8n-nodes-base.httpRequest','typeVersion':4.2,
       'position':[240,0],'parameters':{'method':'POST','url':'http://approval:8000/api/demo/advance',
        'authentication':'genericCredentialType','genericAuthType':'httpHeaderAuth','sendBody':True,'specifyBody':'json',
        'jsonBody':"={{ JSON.stringify({request_id:$json.body.request_id}) }}",'options':{'timeout':35000}}},
      {'id':'p12-result','name':'Human Approval result','type':'n8n-nodes-base.code','typeVersion':2,
       'position':[480,0],'parameters':{'jsCode':"return [{json:{...$json,n8n_execution_id:$execution.id}}];"}}],
     'connections':{'Committed Human Decision':{'main':[[{'node':'Publish only approved report','type':'main','index':0}]]},
      'Publish only approved report':{'main':[[{'node':'Human Approval result','type':'main','index':0}]]}},
     'settings':{'executionOrder':'v1','executionTimeout':120,'saveDataErrorExecution':'all','saveDataSuccessExecution':'all'},'pinData':{}}
    return create,decision


def prepare():
    p1.require(not PRIVATE.exists(),'existing-P12-config-preserved')
    PRIVATE.mkdir()
    database='raa_wp4_dispatch_test_'+uuid4().hex[:12]
    config={'database':database,'stores':{},'portal_key':secrets.token_hex(32),
     'service_token':secrets.token_hex(32),'callback_token':secrets.token_hex(32),
     'primary_token':(p1.PRIVATE/'api/token').read_text().strip(),'reviewer_id':str(uuid4())}
    for kind in FUNCTIONS:
        config['stores'][kind]={'host':'postgres','dbname':database,'user':'raa_wp4_portal_test_'+uuid4().hex[:12],
                                'password':secrets.token_hex(32)}
    owner=secrets.token_hex(32)
    (PRIVATE/'owner-token').write_text(owner+'\n')
    config['owner_hash']=sha256(owner.encode()).hexdigest()
    (PRIVATE/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    for name,w in zip(('p12_create_report.json','p12_human_decision.json'),workflow_sources()):
        (ROOT/'workflows'/name).write_text(json.dumps(w,indent=2)+'\n')
    print('PREPARED|P12-fresh-demo-owner-and-scoped-credentials|sanitized-workflows|no-Docker-mutation')


def config():
    import re
    c=json.loads((PRIVATE/'config.json').read_text())
    p1.require(re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}',c['database']) is not None,'generated-demo-DB')
    p1.require(set(c['stores'])==set(FUNCTIONS),'exact-store-inventory')
    for s in c['stores'].values():
        p1.require(s['host']=='postgres' and s['dbname']==c['database'] and
            re.fullmatch(r'raa_wp4_portal_test_[a-f0-9]{12}',s['user']) is not None and
            re.fullmatch(r'[a-f0-9]{64}',s['password']) is not None,'generated-scoped-store')
    return c


def migration(version):
    files=list((ROOT/'db/migrations').glob(f'{version:03d}_*.sql'))
    p1.require(len(files)==1,'one-migration-per-version')
    return files[0].read_text(encoding='utf-8')


def provision():
    p1.guard(); c=config(); db=c['database']
    p1.require(p1.sql('SELECT max(version) FROM retail.schema_migrations;')=='14','unapplied-P12-only')
    p1.require(p1.sql("SELECT count(*) FROM pg_database WHERE datname='"+db+"';",'n8n')=='0','fresh-approval-DB-only')
    for version in range(15,21):
        print('APPLY|P12-demo-foundation|'+str(version),flush=True)
        p1.sql('BEGIN;\n'+migration(version)+'\nCOMMIT;')
    schema=p1.docker(['exec',p1.PG,'pg_dump','-U','g0_user','-d','raa_wp2_validation','--schema-only','--schema=retail','--no-owner'])
    p1.docker(['exec',p1.PG,'createdb','-U','g0_user',db])
    def sql(value):return p1.sql(value,db)
    sql(schema)
    sql("INSERT INTO retail.schema_migrations(version,name) VALUES(20,'portal_decision_projection');")
    stage=migration(21)
    p1.require(stage.count('raa_wp2_validation')==5,'existing-isolated-deployment-binding')
    sql('BEGIN;\n'+stage.replace('raa_wp2_validation',db)+'\nCOMMIT;')
    for version in range(22,29):
        print('APPLY|P12-new-approval-DB|'+str(version),flush=True)
        sql('BEGIN;\n'+migration(version)+'\nCOMMIT;')
    sql((ROOT/'db/demo/p12_report_binding.sql').read_text())
    p1.require(sql('SELECT count(*) FROM retail.owner_credentials;')=='0','no-copied-owner-authority')
    sql("INSERT INTO retail.owner_credentials(reviewer_id,token_sha256) VALUES('"+c['reviewer_id']+"','"+c['owner_hash']+"');"
        "INSERT INTO retail.approval_policies VALUES('local-publication-v1','"+c['reviewer_id']+"',86400);"
        "INSERT INTO retail.portal_publication_policies_v2 VALUES('owner-portal-acceptance-v2','"+c['reviewer_id']+"',86400);")
    sql('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA retail FROM PUBLIC; REVOKE TEMP,CREATE ON DATABASE '+db+' FROM PUBLIC;')
    for kind,signatures in FUNCTIONS.items():
        s=c['stores'][kind]; role=s['user']; password=s['password']
        sql('CREATE ROLE '+role+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4 PASSWORD '"+password+"';"
            'GRANT CONNECT ON DATABASE '+db+' TO '+role+'; GRANT USAGE ON SCHEMA retail TO '+role+';'
            'ALTER ROLE '+role+' IN DATABASE '+db+" SET default_transaction_read_only=on;"
            'ALTER ROLE '+role+' IN DATABASE '+db+" SET statement_timeout='5s';"
            'ALTER ROLE '+role+' IN DATABASE '+db+" SET lock_timeout='1s';")
        if signatures:sql('GRANT EXECUTE ON FUNCTION '+','.join('retail.'+v for v in signatures)+' TO '+role+';')
    (PRIVATE/'provisioned.json').write_text(json.dumps({'database':db,'source_schema_only':True,'fresh_owner':True})+'\n')
    print('PROVISIONED|P12-demo-only|schema-only-no-authority-copy|fresh-owner|unchanged-existing-guards')


def repair_read_scope():
    """One separately approved additive read grant; no restart or other mutation."""
    p1.guard(); c=config(); db=c['database']; role=c['stores']['reader']['user']
    receipt=json.loads((PRIVATE/'provisioned.json').read_text())
    p1.require(receipt['database']==db and receipt['fresh_owner'] is True,'provisioned-demo-binding')
    fn='retail.api_owner_portal_transition_v1(text,uuid)'
    p1.require(p1.sql("SELECT has_function_privilege('"+role+"','"+fn+"','EXECUTE');",db)=='f','only-missing-read-grant')
    p1.require(p1.sql('SELECT max(version) FROM retail.schema_migrations;',db)=='28','existing-guards-required')
    p1.sql('GRANT EXECUTE ON FUNCTION '+fn+' TO '+role+';',db)
    print('PASS|P12-one-demo-reader-provenance-grant|no-restart')


def install():
    p1.guard(); c=config()
    p1.require((PRIVATE/'provisioned.json').is_file(),'P12-provisioned-required')
    p1.require(p1.docker(['inspect',N8N,'--format','{{index .Config.Labels "com.docker.compose.project"}}']).strip()=='raa-p1-demo','demo-n8n-only')
    p1.require(p1.sql("SELECT count(*) FROM execution_entity WHERE status IN ('running','waiting','new');",'n8n')=='0','idle-demo-n8n-required')
    p1.require(p1.sql("SELECT count(*) FROM workflow_entity WHERE id IN ('"+CREATE+"','"+DECISION+"');",'n8n')=='0','new-workflow-identities-only')
    creds=[]
    for identity,name,header,value in (
        ('p12-primary','P12 demo report API','Authorization','Bearer '+c['primary_token']),
        ('p12-service','P12 demo approval service','Authorization','Bearer '+c['service_token'])):
        creds.append({'id':identity,'name':name,'type':'httpHeaderAuth','data':{'name':header,'value':value}})
    p1.docker(['exec','-i',N8N,'n8n','import:credentials','--input=/dev/stdin'],json.dumps(creds))
    approval='raa-p1-demo-approval-1'
    p1.require(p1.docker(['inspect',approval,'--format','{{index .Config.Labels "com.docker.compose.project"}}']).strip()=='raa-p1-demo','demo-approval-only')
    networks=json.loads(p1.docker(['inspect',approval,'--format','{{json .NetworkSettings.Networks}}']))
    p1.require(set(networks)=={'raa-p1-demo_default','raa-p1-demo_access'},'exact-demo-approval-networks')
    import ipaddress
    ips=[str(ipaddress.IPv4Address(v['IPAddress'])) for v in networks.values()]
    for filename in ('p12_create_report.json','p12_human_decision.json'):
        w=json.loads((ROOT/'workflows'/filename).read_text())
        p1.require(w['active'] is False and not w['pinData'] and all('credentials' not in n for n in w['nodes']),'sanitized-source')
        for n in w['nodes']:
            if n['type']=='n8n-nodes-base.webhook':
                n['parameters']['options']['ipWhitelist']=','.join(ips)
            kind='p12-service' if n['parameters'].get('url','').startswith('http://approval:') else 'p12-primary'
            if n['type']=='n8n-nodes-base.httpRequest':
                cred=next(v for v in creds if v['id']==kind)
                n['credentials']={'httpHeaderAuth':{k:cred[k] for k in ('id','name')}}
        p1.docker(['exec','-i',N8N,'n8n','import:workflow','--input=/dev/stdin'],json.dumps(w))
    p1.docker(['exec',N8N,'n8n','publish:workflow','--id='+DECISION])
    print('INSTALLED|P12-only|owner-credential-not-in-n8n|decision-webhook-published|demo-n8n-restart-required')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('prepare','provision','install','repair_read_scope'))
    args=parser.parse_args()
    try:globals()[args.operation]()
    except Exception:
        raise SystemExit('BLOCKED|P12-'+args.operation+'|details-suppressed|preserve-resources') from None
