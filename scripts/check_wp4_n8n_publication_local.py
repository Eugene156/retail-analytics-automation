"""Actual manual n8n -> isolated worker HTTP -> synthetic SQL acceptance only."""
from copy import deepcopy
import json
from pathlib import Path
import re
import time

from check_wp4_portal_publication_local import provision_portal
from wp2_api_local import docker
from wp3_n8n_local import ROOT,N8N,PG,IMAGE_ID,CheckFailure,expect,invoke,sql,extract_json

SERVER='raa-wp4-portal-test'
API_IMAGE='sha256:aaa61ac9d4ba0a80cbb539ec7b673e8fc1e17c1caa765482d8bb175387745cfb'
SOURCE=ROOT/'workflows'/'wp4_manual_portal_publication.json'
WORKFLOW='raa-wp4-manual-portal-publication-v1'
HTTP={'Read state','Accept approved action'}


def source():
    w=json.loads(SOURCE.read_text(encoding='utf-8'))
    expect(w['id']==WORKFLOW and w['active'] is False and not w['pinData'],'scoped-inactive-source')
    expect(all('credentials' not in n for n in w['nodes']),'unbound-source')
    return w


def import_workflow(credential,plan=None):
    w=source()
    for n in w['nodes']:
        if n['name'] in HTTP:n['credentials']={'httpHeaderAuth':credential}
        if plan is not None and n['name']=='Approved action input':
            n['parameters']['jsCode']='return [{json:'+json.dumps(plan)+'}];'
    invoke(['exec','-i',N8N,'n8n','import:workflow','--input=/dev/stdin'],json.dumps(w))
    expect(sql("SELECT active FROM workflow_entity WHERE id='"+WORKFLOW+"';")=='f','inactive-import')


def request(config,path,value=None):
    code="""
import json,sys
from urllib.request import Request,urlopen
try:
 p=json.loads(sys.stdin.read())
 r=Request('http://raa-wp4-portal-test:8000'+p['path'],headers={'Authorization':'Bearer '+p['token'],'Content-Type':'application/json'},
   data=None if p['value'] is None else json.dumps(p['value']).encode())
 with urlopen(r,timeout=10) as response:print(response.read().decode())
except Exception:raise SystemExit('FAIL|private-worker-request') from None
"""
    return json.loads(invoke(['exec','-i','raa-wp2-api','python','-c',code],
        json.dumps({'path':path,'value':value,'token':config['worker_token']})).stdout)


def execute(workflow=WORKFLOW):
    expect(sql('SELECT count(*) FROM workflow_entity WHERE active;')=='0','no-active-workflows')
    expect(sql("SELECT count(*) FROM execution_entity WHERE status IN ('running','waiting','new');")=='0','no-inflight-executions')
    running=invoke(['inspect',N8N,'--format','{{.State.Running}}']).stdout.strip()=='true'
    if running:invoke(['stop',N8N])
    try:
        result=invoke(['compose','--env-file',str(ROOT/'.local/g0/.env'),'-f',str(ROOT/'g0/compose.yaml'),
            'run','--rm','--no-deps','--use-aliases','-T','n8n','execute','--id='+workflow,'--rawOutput'],allow_failure=True)
    finally:
        if running:invoke(['start',N8N])
    return result.returncode,extract_json(result.stdout,lambda v:isinstance(v,dict) and isinstance(v.get('data'),dict) and 'resultData' in v['data'])


def count(config,action):
    output=docker(['exec',PG,'psql','-X','-qAt','-U','g0_user','-d',config['database'],'-c',
        "BEGIN READ ONLY; SELECT count(*) FROM retail.portal_publications_v2 WHERE action_id='"+action+"'; COMMIT;"])
    return int(output)


def main():
    expect(invoke(['inspect',N8N,'--format','{{.Image}}']).stdout.strip()==IMAGE_ID,'pinned-n8n')
    expect(sql('SELECT count(*) FROM workflow_entity WHERE active;')=='0','idle-instance')
    expect(sql("SELECT count(*) FROM execution_entity WHERE status IN ('running','waiting','new');")=='0','idle-executions')
    existing=sql("SELECT name FROM workflow_entity WHERE id='"+WORKFLOW+"';")
    expect(existing in ('',source()['name']),'owned-workflow-id')
    expect(SERVER not in invoke(['ps','-a','--format','{{.Names}}']).stdout.splitlines(),'unused-isolated-server-name')
    config=provision_portal(worker=True)
    plans=json.loads(invoke(['exec','-i','raa-wp2-api','python','tests/wp4_publication_n8n_fixtures.py'],json.dumps(config)).stdout)
    for p in plans.values():
        expect(re.fullmatch(r'[a-f0-9-]{36}',p['action_id']) is not None,'synthetic-action-id')
    suffix=config['database'].rsplit('_',1)[-1]
    private=ROOT/'.local'/'wp4-n8n'/suffix; private.mkdir(parents=True,exist_ok=False)
    # Runtime-generated ignored config: worker rights only, no admin/owner token.
    (private/'worker.json').write_text(json.dumps({n:config[n] for n in ('database','portal_worker','worker_token')}|
        {'allowed_actions':[p['action_id'] for p in plans.values()]}),encoding='utf-8')
    credential={'id':'raa-wp4-worker-'+suffix,'name':'WP4 isolated worker '+suffix}
    invoke(['exec','-i',N8N,'n8n','import:credentials','--input=/dev/stdin'],json.dumps([dict(credential,type='httpHeaderAuth',
        data={'name':'Authorization','value':'Bearer '+config['worker_token']})]))
    invoke(['run','--detach','--name',SERVER,'--network','raa-g0_default','--label','io.raa.test-scope=wp4-portal-worker',
        '--user','65532:65532','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--memory','256m',
        '--cpus','0.5','--pids-limit','64','--tmpfs','/tmp:rw,noexec,nosuid,size=16m',
        '--mount','type=bind,src='+str(ROOT/'api')+',dst=/app/api,readonly',
        '--mount','type=bind,src='+str(ROOT/'tests')+',dst=/app/tests,readonly',
        '--mount','type=bind,src='+str(private)+',dst=/run/worker,readonly',
        '--env','PYTHONDONTWRITEBYTECODE=1','--entrypoint','python',API_IMAGE,'tests/wp4_portal_worker_http.py'])
    try:
        for _ in range(40):
            try:request(config,'/api/__test/observations');break
            except CheckFailure:time.sleep(.25)
        else:raise CheckFailure('worker-server-readiness')
        for scenario in ('normal','normal_replay','state_retry503','retry503','lost_ack','exhaust503','permanent401','expired'):
            name='normal' if scenario=='normal_replay' else scenario
            p=plans[name]
            request(config,'/api/__test/configure',{'mode':name if name not in ('normal','expired') else 'normal','action_id':p['action_id']})
            import_workflow(credential,p)
            exit_code,execution=execute(); data=execution['data']['resultData']
            calls=request(config,'/api/__test/observations')['calls']; posts=[c for c in calls if c['method']=='POST']
            expect(all(c['key']==p['acceptance_key'] and c['action_id']==p['action_id'] for c in calls),'stable-action-and-key')
            expect(calls and calls[0]['method']=='GET','reconcile-before-first-write')
            for i,c in enumerate(calls):
                if c['method']=='POST':expect(i>0 and calls[i-1]['method']=='GET','reconcile-between-posts')
            success=scenario in ('normal','normal_replay','state_retry503','retry503','lost_ack')
            expect((exit_code==0 and 'error' not in data)==success,'expected-execution-outcome')
            expected_posts={'normal':1,'normal_replay':0,'state_retry503':1,'retry503':2,'lost_ack':1,'exhaust503':3,'permanent401':1,'expired':0}[scenario]
            expect(len(posts)==expected_posts,'bounded-actual-post-count')
            expect(count(config,p['action_id'])==(1 if success else 0),'actual-sql-single-effect')
            if success:
                expect(data['lastNodeExecuted']=='Verified committed publication','reconciled-success-node')
                summary=data['runData']['Verified committed publication'][0]['data']['main'][0][0]['json']
                expect(summary['action_id']==p['action_id'] and summary['automatic_approval'] is False and summary['physical_export'] is False,'safe-terminal-summary')
            if scenario=='retry503':expect(posts[1]['seconds']-posts[0]['seconds']>=1,'actual-Retry-After-wait')
            if scenario=='state_retry503':expect(calls[1]['seconds']-calls[0]['seconds']>=1,'actual-state-Retry-After-wait')
            print('PASS|actual-n8n-isolated-SQL-HTTP|'+scenario+'|POSTs='+str(len(posts)),flush=True)
        import_workflow(credential)
        actual=extract_json(invoke(['exec',N8N,'n8n','export:workflow','--id='+WORKFLOW,'--output=/dev/stdout']).stdout,
                            lambda v:isinstance(v,list) and len(v)==1 and v[0].get('id')==WORKFLOW)[0]
        for n in actual['nodes']:n.pop('credentials',None)
        expect(all(actual[k]==source()[k] for k in ('id','name','nodes','connections','settings')),'sanitized-real-export-roundtrip')
        invoke(['logs',SERVER])
        print('PASS|actual-n8n-sanitized-roundtrip|inactive-null-plan|no-main-action',flush=True)
    finally:
        # Restore a non-executable null plan even on failed checks; preserve history.
        import_workflow(credential)
        label=invoke(['inspect',SERVER,'--format','{{index .Config.Labels "io.raa.test-scope"}}']).stdout.strip()
        expect(label=='wp4-portal-worker','exact-created-container-cleanup')
        invoke(['stop',SERVER]); invoke(['rm',SERVER])
    print('Test database/logins/credential/history/private worker config retained: '+config['database'])


if __name__=='__main__':
    try:main()
    except CheckFailure as e:raise SystemExit('FAIL|'+str(e)) from None
    except Exception:raise SystemExit('FAIL|isolated-n8n-publication|details-suppressed-to-protect-secrets') from None
