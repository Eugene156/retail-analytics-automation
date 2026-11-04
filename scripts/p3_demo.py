"""Demo-only MCP preparation; start/deploy need separate Docker approval."""
import argparse
from copy import deepcopy
import json
import secrets

import p1_demo as p1
import p2_demo as p2
import read_tool_answer as answer

TOKEN = p1.PRIVATE / 'api/p3-mcp-token'
PARENT = 'p3-mcp-agent-demo-v1'
CORE = 'p3-mcp-agent-core-v1'
N8N = 'raa-p1-demo-n8n-1'


def workflows():
    parent, core = deepcopy(p2.workflows())
    parent.update(id=PARENT, name='P3 MCP AI Agent - Manual Demo')
    core.update(id=CORE, name='P3 MCP AI Agent - Integrated Core')
    core['settings']['callerIds'] = PARENT
    parent['nodes'][-1]['parameters']['workflowId']['value'] = CORE
    core['nodes'] = [n for n in core['nodes'] if n['type'] != 'n8n-nodes-base.httpRequestTool']
    for name in ('Get_Sales_KPIs', 'Get_Data_Quality'):
        core['connections'].pop(name)
    for n in core['nodes']:
        if n['name'] == 'Validate question':
            n['parameters']['jsCode'] = n['parameters']['jsCode'].replace('P2 Manual Demo', 'P3 MCP Manual Demo')
        if n['name'] == 'AI Agent':
            n['parameters']['options']['systemMessage'] = answer.prompt(True)
        if n['name'] == 'Validate tool evidence':
            n['parameters']['jsCode'] = """const r=$json;const steps=r.intermediateSteps||[];
const names={'MCP_Client_Tool_get_sales_kpis':'get_sales_kpis','MCP_Client_Tool_get_data_quality':'get_data_quality'};
if(typeof r.output!=='string'||!r.output.trim()||r.output.length>3000||!steps.length||steps.length>2)throw new Error('Invalid model answer or actual tool evidence');
const facts={};
for(const s of steps){
 if(!names[s.action?.tool]||!s.observation)throw new Error('Unknown or missing MCP tool evidence');
 const results=JSON.parse(s.observation);
 const body=results?.[0]?.structuredContent;
 const section=names[s.action.tool]==='get_sales_kpis'?'kpis':'quality';
 if(results.length!==1||body?.schema_version!=='p2-read-tool-v1'||body?.access!=='read-only'||!body[section])throw new Error('Invalid MCP read response');
 if(section==='kpis'){
  for(const [label,key,money] of [['Sale rows','sale_rows',false],['Net recorded sales','net_recorded_sales_gbp',true],['Gross sales','sales_value_gbp',true],['Cancellation rows','cancellation_rows',false],['Cancellation magnitude','cancellation_magnitude_gbp',true]])facts[label]={value:String(body.kpis[key]),money};
 }else{
  facts['Quality findings']={value:String(body.quality.finding_rows),money:false};
  facts['Missing customer sale rows']={value:String(body.missing_customer_sale_rows),money:false};
 }
}
const actual=[...new Set(steps.map(s=>names[s.action.tool]))].sort();
if(actual.length!==steps.length)throw new Error('Repeated tool call denied');
// Fail closed on numeric contradictions; never rewrite the model or MCP output.
const lines=r.output.trim().split(/\\r?\\n/);const seen=new Set();
if(lines.length!==Object.keys(facts).length)throw new Error('Answer must contain exactly the evidenced facts');
for(const line of lines){
 const match=line.trim().match(/^([A-Za-z ]+):\\s*(GBP )?(-?\\d+(?:\\.\\d+)?)$/);
 const fact=match&&facts[match[1]];
 if(!fact||seen.has(match[1])||Boolean(match[2])!==fact.money||match[3]!==fact.value)throw new Error('Answer contradicts MCP numeric facts');
 seen.add(match[1]);
}
return [{json:{status:'PASS',answer:r.output,tools_used:actual,intermediateSteps:steps,access:'read-only',numeric_consistency:'PASS'}}];"""
    validation = next(n for n in core['nodes'] if n['name']=='Validate tool evidence')
    validation['parameters']['jsCode'] = answer.wrap_guard(validation['parameters']['jsCode'], True)
    core['nodes'].append(p2.node('MCP Client Tool', '@n8n/n8n-nodes-langchain.mcpClientTool', 1.4, [570, 260],
                                {'endpointUrl': 'http://127.0.0.1:8002/mcp', 'serverTransport': 'httpStreamable',
                                 'authentication': 'headerAuth', 'include': 'all', 'options': {'timeout': 150000}}))
    core['connections']['MCP Client Tool'] = {'ai_tool': [[{'node': 'AI Agent', 'type': 'ai_tool', 'index': 0}]]}
    return parent, core


def prepare():
    if not TOKEN.exists():
        TOKEN.write_text(secrets.token_hex(32) + '\n')
    for name, workflow in zip(('p3_mcp_agent_demo.json', 'p3_mcp_agent_core.json'), workflows()):
        (p1.ROOT / 'workflows' / name).write_text(json.dumps(workflow, indent=2) + '\n')
    print('PREPARED|new-scoped-token|P3-only-exports|no-Docker-changes')


def guard():
    p1.guard()
    assert p1.docker(['inspect', N8N, '--format', '{{index .Config.Labels "com.docker.compose.project"}}']).strip() == 'raa-p1-demo'


def start():
    guard()
    check = "const net=require('net');const s=net.connect(8002,'127.0.0.1');s.on('connect',()=>{s.destroy();process.exit(1)});s.on('error',e=>process.exit(e.code==='ECONNREFUSED'?0:2));"
    p1.docker(['exec', N8N, 'node', '-e', check])  # Abort if occupied; no duplicate.
    config = {'apiToken': p2.TOKEN.read_text().strip(), 'mcpToken': TOKEN.read_text().strip()}
    assert all(len(value) == 64 for value in config.values())
    source = 'const P3_CONFIG=' + json.dumps(config) + ';\n' + (p1.ROOT / 'scripts/p3_mcp_server.js').read_text()
    # Detached docker exec does not forward stdin. A short foreground bootstrap
    # feeds the child privately, closes stdin, then releases its process handle.
    bootstrap = "const {spawn}=require('node:child_process');const child=spawn(process.execPath,['--max-old-space-size=96','-'],{detached:true,stdio:['pipe','ignore','ignore']});child.stdin.end(" + json.dumps(source) + ");child.unref();"
    p1.docker(['exec', '-i', N8N, 'node', '-'], bootstrap)
    print('STARTED|loopback-only8002|bundled-MCP-SDK|no-secret-argv-or-logs')


def deploy():
    guard()
    prepared = workflows()
    for filename, workflow in zip(('p3_mcp_agent_demo.json', 'p3_mcp_agent_core.json'), prepared):
        assert json.loads((p1.ROOT / 'workflows' / filename).read_text()) == workflow
    assert p1.sql("SELECT count(*) FROM workflow_entity WHERE id IN ('" + PARENT + "','" + CORE + "');", 'n8n') == '0'
    assert p1.sql("SELECT count(*) FROM credentials_entity WHERE id='p3-mcp';", 'n8n') == '0'
    assert p1.sql("SELECT count(*) FROM credentials_entity WHERE id='p2-ollama' AND type='ollamaApi';", 'n8n') == '1'
    credential = {'id': 'p3-mcp', 'name': 'P3 loopback read MCP only', 'type': 'httpHeaderAuth',
                  'data': {'name': 'Authorization', 'value': 'Bearer ' + TOKEN.read_text().strip()}}
    p1.docker(['exec', '-i', N8N, 'n8n', 'import:credentials', '--input=/dev/stdin'], json.dumps([credential]))
    for workflow in prepared:
        for n in workflow['nodes']:
            if n['name'] == 'MCP Client Tool':
                n['credentials'] = {'httpHeaderAuth': {'id': credential['id'], 'name': credential['name']}}
            elif n['name'] == 'Ollama Chat Model':
                n['credentials'] = {'ollamaApi': {'id': 'p2-ollama', 'name': 'P2 local Ollama'}}
        p1.docker(['exec', '-i', N8N, 'n8n', 'import:workflow', '--input=/dev/stdin'], json.dumps(workflow))
    print('DEPLOYED|one-new-credential|two-new-P3-workflows|P1-P2-preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'start', 'deploy'))
    args = parser.parse_args()
    try:
        globals()[args.operation]()
    except Exception:
        raise SystemExit('BLOCKED|P3-' + args.operation + '|details-suppressed|preserve-state') from None
