"""Demo-only n8n HTTP context containment; deploy requires separate Docker approval.

Never prints secrets, exports old executions or removes retained state.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import secrets

import p1_demo as p1
import p12_demo as p12

PRIVATE=p12.PRIVATE/'token-repair.json'
WORKER='p12-report-core-v2'
GUARD="if ($execution.mode !== 'production') throw new Error('Use P1.2 Create Report; direct HTTP workflow testing is blocked');\n"


def sources():
    core=deepcopy(p12.workflow_sources()[0])
    core['id']=WORKER; core['name']='P1.2 Report Core - Integrated Only'
    trigger=next(n for n in core['nodes'] if n['type']=='n8n-nodes-base.manualTrigger')
    trigger['type']='n8n-nodes-base.executeWorkflowTrigger'; trigger['typeVersion']=1.1
    trigger['parameters']={'inputSource':'passthrough'}
    for node in core['nodes']:
        if node['name']=='Prepare request':node['parameters']['jsCode']=GUARD+node['parameters']['jsCode']
    core['settings'].update({'saveDataSuccessExecution':'all','saveDataErrorExecution':'all','callerPolicy':'workflowsFromAList','callerIds':p12.CREATE})
    parent={'id':p12.CREATE,'name':'P1.2 Create Report for Human Approval','active':False,
      'nodes':[{'id':'p12-manual','name':'Manual Trigger','type':'n8n-nodes-base.manualTrigger','typeVersion':1,'position':[0,0],'parameters':{}},
       {'id':'p12-core-call','name':'Create verified report and approval request','type':'n8n-nodes-base.executeWorkflow','typeVersion':1.3,'position':[240,0],
        'parameters':{'source':'database','workflowId':{'__rl':True,'value':WORKER,'mode':'id'},'mode':'once','options':{'waitForSubWorkflow':True}}}],
      'connections':{'Manual Trigger':{'main':[[{'node':'Create verified report and approval request','type':'main','index':0}]]}},
      'settings':{'executionOrder':'v1','executionTimeout':240,'saveDataSuccessExecution':'all','saveDataErrorExecution':'all'},'pinData':{}}
    return core,parent


def prepare():
    p1.require(not PRIVATE.exists(),'existing-rotation-preserved')
    c=p12.config(); old=(p1.PRIVATE/'api/token').read_text().strip()
    p1.require(old==c['primary_token'],'current-demo-token-binding')
    PRIVATE.write_text(json.dumps({'old_token':old,'new_token':secrets.token_hex(32),'state':'prepared'},indent=2)+'\n')
    for filename,workflow in zip(('p12_report_core.json','p12_create_report.json'),sources()):
        (p1.ROOT/'workflows'/filename).write_text(json.dumps(workflow,indent=2)+'\n')
    print('PREPARED|ignored-fresh-token|supported-integrated-workflow|no-live-rotation-or-Docker-mutation')


def deploy():
    p1.guard(); c=p12.config(); r=json.loads(PRIVATE.read_text())
    p1.require(r['state']=='prepared' and c['primary_token']==r['old_token'],'one-time-token-repair')
    for container in (p12.N8N,'raa-p1-demo-api-1','raa-p1-demo-approval-1'):
        p1.require(p1.docker(['inspect',container,'--format','{{index .Config.Labels "com.docker.compose.project"}}']).strip()=='raa-p1-demo','owned-demo-only')
    p1.require(p1.sql("SELECT count(*) FROM execution_entity WHERE status IN ('running','waiting','new');",'n8n')=='0','idle-demo-required')
    p1.require(p1.sql("SELECT count(*) FROM workflow_entity WHERE id='"+WORKER+"';",'n8n')=='0','new-core-identity')
    p1.require(p1.sql("SELECT count(*) FROM workflow_entity WHERE id='"+p12.CREATE+"' AND active=false;",'n8n')=='1','inactive-demo-parent-only')
    core,parent=sources()
    for name,w in [('p12_report_core.json',core),('p12_create_report.json',parent)]:
        p1.require(json.loads((p1.ROOT/'workflows'/name).read_text())==w,'exact-sanitized-workflow')
    credential={'id':'p12-primary','name':'P12 demo report API','type':'httpHeaderAuth','data':{'name':'Authorization','value':'Bearer '+r['new_token']}}
    p1.docker(['exec','-i',p12.N8N,'n8n','import:credentials','--input=/dev/stdin'],json.dumps([credential]))
    for n in core['nodes']:
        if n['type']=='n8n-nodes-base.httpRequest':
            kind='p12-service' if n['parameters']['url'].startswith('http://approval:') else 'p12-primary'
            n['credentials']={'httpHeaderAuth':{'id':kind,'name':'P12 demo approval service' if kind=='p12-service' else 'P12 demo report API'}}
    for w in (core,parent):p1.docker(['exec','-i',p12.N8N,'n8n','import:workflow','--input=/dev/stdin'],json.dumps(w))
    c['primary_token']=r['new_token']
    (p1.PRIVATE/'api/token').write_text(r['new_token']+'\n')
    (p12.PRIVATE/'config.json').write_text(json.dumps(c,indent=2)+'\n')
    r['state']='deployed-awaiting-two-demo-restarts';PRIVATE.write_text(json.dumps(r,indent=2)+'\n')
    print('DEPLOYED|one-supported-header-credential|core-and-parent-only|restart-demo-api-and-approval-required|old-history-retained')


def check():
    p1.guard();c=p12.config();r=json.loads(PRIVATE.read_text())
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    for token,expected in ((r['old_token'],401),(r['new_token'],200)):
        try:
            with urlopen(Request('http://127.0.0.1:18090/readyz',headers={'Authorization':'Bearer '+token}),timeout=10) as response:status=response.status
        except HTTPError as e:status=e.code
        p1.require(status==expected,'actual-token-revocation-and-readiness')
    for identity in (p12.CREATE,WORKER,p12.DECISION):
        history=p1.sql("BEGIN READ ONLY; SELECT coalesce(string_agg(d.data,E'\\n'),'') FROM execution_data d JOIN execution_entity e ON e.id=d.\"executionId\" WHERE e.\"workflowId\"='"+identity+"' AND e.id>9; COMMIT;",'n8n')
        p1.require(history and not any(v in history for v in (r['new_token'],r['old_token'],c['service_token'],c['portal_key'],(p12.PRIVATE/'owner-token').read_text().strip())),'new-execution-history-secret-scan')
    protected=[r['new_token'],c['service_token'],c['portal_key'],(p12.PRIVATE/'owner-token').read_text().strip()]+[s['password'] for s in c['stores'].values()]
    for name in (p12.N8N,'raa-p1-demo-api-1','raa-p1-demo-approval-1'):
        # Docker sends service logs to both stdout and stderr; capture both privately.
        import subprocess
        logged=subprocess.run(['docker','--context','desktop-linux','logs','--since','10m',name],capture_output=True,check=True)
        content=logged.stdout+logged.stderr
        p1.require(not any(value.encode() in content for value in protected),'demo-log-secret-scan')
    p1.require(p1.sql("SELECT count(*) FROM execution_entity WHERE id IN (6,8);",'n8n')=='2','old-executions-retained')
    # Scan Git's tracked/staged bytes without emitting paths/content containing a secret.
    import subprocess
    entries=subprocess.run(['git','ls-files','-z'],capture_output=True,check=True).stdout.split(b'\0')
    for value in (r['old_token'],r['new_token']):
        for name in ('p12_report_core.json','p12_create_report.json','p12_human_decision.json'):
            p1.require(value not in (p1.ROOT/'workflows'/name).read_text(),'sanitized-workflow-secret-scan')
        for raw in entries:
            if not raw:continue
            path=raw.decode('utf-8');local=p1.ROOT/path
            if local.is_file():p1.require(value.encode() not in local.read_bytes(),'tracked-secret-absent')
            stage=subprocess.run(['git','show',':'+path],capture_output=True)
            p1.require(value.encode() not in stage.stdout,'staged-secret-absent')
    print('PASS|old-token-revoked|new-token-ready|new-history-all-three-workflows-clean|Git-clean|old-executions-retained')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=('prepare','deploy','check'));args=parser.parse_args()
    try:globals()[args.operation]()
    except Exception:raise SystemExit('BLOCKED|P12-token-repair-'+args.operation+'|details-suppressed|preserve-state') from None
