"""Targeted real MCP discovery and private P3 history checks."""
import argparse
import json
import subprocess
import p1_demo as p1
import p2_demo as p2
import p3_demo as p3
from check_p2_demo import unflatten


def discovery():
    source = "const TOKEN=" + json.dumps(p3.TOKEN.read_text().strip()) + ";\n" + r"""
const {createRequire}=require('node:module');
const req=createRequire('/usr/local/lib/node_modules/n8n/node_modules/@n8n/n8n-nodes-langchain/package.json');
const {Client}=req('@modelcontextprotocol/sdk/client/index.js');
const {StreamableHTTPClientTransport}=req('@modelcontextprotocol/sdk/client/streamableHttp.js');
(async()=>{
 const client=new Client({name:'raa-p3-read-check',version:'1.0.0'});
 const transport=new StreamableHTTPClientTransport(new URL('http://127.0.0.1:8002/mcp'),{requestInit:{headers:{Authorization:'Bearer '+TOKEN}}});
 await client.connect(transport);
 const result=await client.listTools();
 const names=result.tools.map(t=>t.name).sort();
 if(JSON.stringify(names)!==JSON.stringify(['get_data_quality','get_sales_kpis']))throw Error('Discovery mismatch');
 if(!result.tools.every(t=>t.annotations.readOnlyHint===true && t.annotations.destructiveHint===false))throw Error('Readonly annotations');
 const responses=[];
 for(const name of names){
  const response=await client.callTool({name,arguments:{}});
  if(response.isError)throw Error('Tool error');
  const body=JSON.parse(response.content[0].text);
  if(body.access!=='read-only'||body.schema_version!=='p2-read-tool-v1')throw Error('Tool contract');
  responses.push({method:'tools/call',name,arguments:{},response:body});
 }
 const invalid=await client.callTool({name:'get_sales_kpis',arguments:{sql:'DELETE'}});
 if(!invalid.isError)throw Error('Unexpected argument accepted');
 const anon=await fetch('http://127.0.0.1:8002/mcp',{method:'POST',body:'{}'});
 if(anon.status!==401)throw Error('Anonymous access');
 await client.close();
 console.log(JSON.stringify({discovery:result,requests:responses,unknown_arguments_denied:true,anonymous_status:anon.status}));
})().catch(()=>{console.log('BLOCKED|MCP-probe|details-suppressed');process.exit(1)});
"""
    result=p1.docker(['exec','-i',p3.N8N,'node','-'],source)
    assert p3.TOKEN.read_text().strip() not in result
    proof=json.loads(result)
    (p1.ROOT/'evidence/p3_mcp_discovery.json').write_text(json.dumps(proof,indent=2)+'\n')
    print('PASS|MCP-discovery|two-real-read-calls|anonymous-and-unknown-arguments-denied')


def history(save=False):
    protected=[p3.TOKEN.read_text().strip(),p2.TOKEN.read_text().strip(),(p1.PRIVATE/'api/token').read_text().strip()]
    rows=p1.sql("BEGIN READ ONLY; SELECT json_build_object('id',e.id,'workflow',e.\"workflowId\",'status',e.status,'data',d.data) FROM execution_entity e LEFT JOIN execution_data d ON d.\"executionId\"=e.id WHERE e.\"workflowId\" IN ('"+p3.PARENT+"','"+p3.CORE+"') ORDER BY e.id; COMMIT;",'n8n')
    assert not any(secret in rows for secret in protected),'History secret leak'
    evidence=[]
    for line in rows.splitlines():
        row=json.loads(line)
        item={k:row[k] for k in ('id','workflow','status')}
        if row['data']:
            data=unflatten(row['data']); result=data.get('resultData',{}); runs=result.get('runData',{})
            if result.get('error'): item['error']=str(result['error'].get('message','Execution error'))[:500]
            validated=runs.get('Validate tool evidence',[{}])[-1]
            if validated.get('data'):
                output=validated['data']['main'][0][0]['json']; item.update(output)
            else:
                agent=runs.get('AI Agent',[{}])[-1]
                for branch in agent.get('data',{}).get('main',[]):
                    for entry in branch or []:
                        if 'error' in entry.get('json',{}): item['agent_error']=str(entry['json']['error'])[:500]
            item['mcp_history']=runs.get('MCP Client Tool',[])
        evidence.append(item)
    for container in [p3.N8N,'raa-p1-demo-api-1','raa-p2-demo-ollama-1']:
        logs=subprocess.run(['docker','--context','desktop-linux','logs','--since','30m',container],capture_output=True,check=True)
        assert not any(s.encode() in logs.stdout+logs.stderr for s in protected),'Log secret leak'
    assert p1.sql('SELECT count(*) FROM execution_entity WHERE id IN (6,8);','n8n')=='2'
    credential=p1.sql("SELECT data FROM credentials_entity WHERE id='p3-mcp';",'n8n')
    assert credential and not credential.startswith('{') and not any(s in credential for s in protected)
    assert subprocess.run(['git','check-ignore',str(p3.TOKEN)],capture_output=True).returncode==0
    for filename in subprocess.run(['git','ls-files','-z'],capture_output=True,check=True).stdout.split(b'\0'):
        if not filename: continue
        path=p1.ROOT/filename.decode()
        if path.is_file(): assert not any(s.encode() in path.read_bytes() for s in protected)
        staged=subprocess.run(['git','show',':'+filename.decode()],capture_output=True)
        assert not any(s.encode() in staged.stdout for s in protected)
    for filename in ('p3_mcp_agent_demo.json','p3_mcp_agent_core.json'):
        assert not any(s in (p1.ROOT/'workflows'/filename).read_text() for s in protected)
    for filename in subprocess.run(['git','ls-files','--others','--exclude-standard','-z'],capture_output=True,check=True).stdout.split(b'\0'):
        if not filename: continue
        path=p1.ROOT/filename.decode()
        if path.is_file(): assert not any(s.encode() in path.read_bytes() for s in protected),'Untracked public file secret leak'
    receipt={'secret_scan':'PASS','encrypted_credential':True,'old_executions_retained':True,'executions':evidence}
    if save:
        cores=[e for e in evidence if e['workflow']==p3.CORE and e['status']=='PASS']
        assert any(len(e['tools_used'])==1 for e in cores) and any(set(e['tools_used'])=={'get_sales_kpis','get_data_quality'} for e in cores)
        assert all(e['mcp_history'] for e in cores)
        latest=next(e for e in reversed(evidence) if e['workflow']==p3.CORE)
        assert latest.get('numeric_consistency')=='PASS' and set(latest['tools_used'])=={'get_sales_kpis','get_data_quality'},'New combined execution with numeric consistency required'
        containers=[p3.N8N,'raa-p1-demo-api-1','raa-p1-demo-postgres-1','raa-p1-demo-runner-1','raa-p2-demo-ollama-1']
        runtime=[]
        for container in containers:
            line=p1.docker(['inspect',container,'--format','{{json .State}}|{{.RestartCount}}|{{json .HostConfig.PortBindings}}']).strip()
            state,restarts,ports=line.split('|'); state=json.loads(state); ports=json.loads(ports)
            assert state['Running'] and not state['OOMKilled'] and restarts=='0'
            assert all(p['HostIp']=='127.0.0.1' for values in (ports or {}).values() for p in values or [])
            runtime.append({'container':container,'running':True,'OOMKilled':False,'restart_count':0,'host_ports':ports})
        receipt['runtime']=runtime
        receipt['docker_stats']=p1.docker(['stats','--no-stream','--format','{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}']).strip().splitlines()
        memory=subprocess.run(['powershell','-NoProfile','-Command','[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)'],capture_output=True,check=True,text=True)
        receipt['Windows_free_RAM_GiB']=float(memory.stdout.strip().replace(',','.'))
        (p1.ROOT/'evidence/p3_mcp_agent.json').write_text(json.dumps(receipt,indent=2)+'\n')
    # Bounded output: full requests/responses retained only in sanitized evidence.
    for e in evidence: e.pop('mcp_history',None); e.pop('intermediateSteps',None)
    print(json.dumps(receipt))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('discovery','history','save'))
    operation=parser.parse_args().operation
    p3.guard()
    discovery() if operation=='discovery' else history(operation=='save')
