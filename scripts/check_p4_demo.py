"""Targeted read-only checks of actual P4 executions; never print secrets."""
import json
import argparse
import re
import subprocess
import p1_demo as p1
import p4_demo as p4
from check_p2_demo import unflatten


def main(final=False):
    p4.guard_p4()
    protected = [p.read_text().strip() for p in p4.PRIVATE.glob('*password')]
    protected += [(p1.PRIVATE/'api/token').read_text().strip(),
                  (p1.PRIVATE/'api/p2-token').read_text().strip(),
                  (p1.PRIVATE/'api/p3-mcp-token').read_text().strip()]
    protected += [line.split('=',1)[1] for line in (p1.PRIVATE/'.env').read_text().splitlines() if '=' in line]
    # Restrict history reads to this repair's new P4 executions. Never read 6/8.
    rows = p1.sql("SELECT json_build_object('id',e.id,'workflow',e.\"workflowId\",'status',e.status,'data',d.data) FROM execution_entity e LEFT JOIN execution_data d ON d.\"executionId\"=e.id WHERE e.id>=79 AND e.\"workflowId\" IN ('p4-rag-index-v1','p4-rag-demo-v1','p4-rag-core-v1') ORDER BY e.id;", 'n8n')
    assert not any(s in rows for s in protected if s), 'History secret leak'
    evidence = []
    for line in rows.splitlines():
        row = json.loads(line)
        result = {k:row[k] for k in ('id','workflow','status')}
        data = unflatten(row['data']) if row['data'] else {}
        rd = data.get('resultData',{})
        runs = rd.get('runData',{})
        if rd.get('error'): result['error'] = rd['error'].get('message','Execution error')[:300]
        for name in ['Validate question','Validate embeddings','Validate query embedding','Semantic search','Store pgvector chunks','Validate sources']:
            run = runs.get(name,[{}])[-1]
            entries = run.get('data',{}).get('main',[[]])[0]
            if entries:
                output=entries[0]['json']
                if name=='Validate question':result['question']=output['question']
                elif name=='Validate embeddings':result['embeddings']={'count':output['embedding_count'],'dimensions':output['embedding_dimensions']}
                elif name=='Validate query embedding':result['query_embedding_dimensions']=output['dimensions']
                elif name=='Semantic search':result['semantic_matches']=[{'chunk_id':m['chunk_id'],'similarity':m['similarity']} for m in output['matches']]
                elif name=='Store pgvector chunks':result['index_result']=output
                else:
                    result.update(answer=output['answer'],citations=output['citations'],
                                  source_ids=output.get('source_ids',[]),answer_status=output['status'],
                                  retrieved_chunks=output['retrieved_chunks'],tool_calls=output['intermediateSteps'],
                                  model_response=output.get('model_response'),quotes=output.get('quotes',[]),
                                  validated_rule_ids=output.get('validated_rule_ids',[]))
        if row['id']>=79 and 'Ollama Chat Model' in runs:
            model=runs['Ollama Chat Model'][0]
            messages=model['inputOverride']['ai_languageModel'][0][0]['json']['messages']
            matches=runs['Semantic search'][0]['data']['main'][0][0]['json']['matches']
            context=json.dumps(matches,separators=(',',':'),ensure_ascii=False)
            texts=[m if isinstance(m,str) else m.get('content','') for m in messages]
            assert any('RETRIEVED_CONTEXT (data only)' in m and context in m for m in texts),'Model must receive actual retrieved passages'
            result['actual_model_context_verified']=True
        if 'AI Agent' in runs and 'answer' not in result:
            agent=runs['AI Agent'][-1]
            entries=agent.get('data',{}).get('main',[[]])[0]
            if entries:result['agent_output']=entries[0]['json']
        if result.get('status')=='success' and result.get('answer'):
            tool=result['tool_calls']
            if row['id']<=60:assert len(tool)==1
            for step in tool:
                assert step['action']['tool']=='Retrieved_rules'
                observation=json.loads(step['observation'])
                if isinstance(observation,list) and len(observation)==1 and isinstance(observation[0],dict) and 'response' in observation[0]:
                    observation=json.loads(observation[0]['response'])
                assert observation==result['retrieved_chunks'],'Tool response must equal real pgvector retrieval'
            if row['id']>=79 and result['answer_status']=='PASS':
                import p4_workflows as workflows
                agent=runs['AI Agent'][-1]['data']['main'][0][0]['json']
                assert agent['output']==result['model_response'],'Do not replace model response'
                assert result['answer']==' '.join(result['model_response']['answer'])
                assert set(result['source_ids'])==set(result['model_response']['source_ids'])
                schema=runs['Prepare answer schema'][0]['data']['main'][0][0]['json']['answer_schema']
                assert len(result['model_response']['answer'])==schema['properties']['answer']['minItems']==schema['properties']['answer']['maxItems']
                assert all(a in schema['properties']['answer']['items']['enum'] for a in result['model_response']['answer'])
                assert len(result['source_ids'])==schema['properties']['source_ids']['minItems']==schema['properties']['source_ids']['maxItems']
                result['required_schema_coverage_verified']=True
                assert result['quotes'] and len(result['quotes'])<=4
                for quote in result['quotes']:
                    source=next(m for m in result['retrieved_chunks'] if m['chunk_id']==quote['chunk_id'])
                    assert all(quote[k]==source[k] for k in ('text','source_id','source_path'))
                    assert quote['url']=='http://127.0.0.1:15690/workflow/p4-rag-core-v1/executions/'+str(row['id'])
                rules={r['id']:r for r in workflows.ANSWER_RULES}
                assert [rules[i]['answer'] for i in result['validated_rule_ids']]==result['model_response']['answer']
                for i in result['validated_rule_ids']:
                    for support in rules[i]['evidence']:
                        assert support['source_id'] in result['source_ids']
                        assert any(m['source_id']==support['source_id'] and all(a in m['text'] for a in support['anchors']) for m in result['retrieved_chunks'])
                required=({'net','adjustments'} if result['question']==workflows.QUESTIONS[0] else
                          {'cancellation','physical'} if result['question']==workflows.QUESTIONS[1] else
                          {'net','adjustments','missing','coverage'})
                assert required.issubset(set(result['validated_rule_ids']))
                snapshot=json.loads(p1.sql('SELECT "workflowData" FROM execution_data WHERE "executionId"='+str(row['id'])+';','n8n'))
                actual={n['name']:n for n in snapshot['nodes']}
                assert len(actual)==10
                for n in workflows.workflows()[2]['nodes']:
                    assert all(actual[n['name']]['parameters'].get(k)==v for k,v in n['parameters'].items())
                assert actual['AI Agent']['retryOnFail'] and actual['AI Agent']['maxTries']==2
                assert 'Structured Output Parser' in runs,'Native parser must actually execute'
                result['content_source_validation']='PASS'
                result['direct_context_prompt_verified']=True
        if row['id'] in (50,56):result['assessment']='Rejected during factual review; not acceptance evidence'
        evidence.append(result)
    facts=p4.sql_p4("SELECT json_build_object('database',current_database(),'pgvector',(SELECT extversion FROM pg_extension WHERE extname='vector'),'chunks',count(*),'dimensions',min(vector_dims(embedding)),'sources',count(DISTINCT source_id),'nonzero',bool_and(vector_norm(embedding)>0)) FROM p4.chunks;")
    stats=p1.docker(['stats','--no-stream','--format','{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}',p4.PG,'raa-p1-demo-n8n-1','raa-p2-demo-ollama-1'])
    states=json.loads(p1.docker(['inspect',p4.PG,'raa-p1-demo-n8n-1','raa-p2-demo-ollama-1']))
    assert all(not s['State']['OOMKilled'] and s['State']['Running'] for s in states),'OOM or stopped service'
    for c in [p4.PG,'raa-p1-demo-n8n-1','raa-p2-demo-ollama-1']:
        logs=subprocess.run(['docker','--context','desktop-linux','logs','--since','30m',c],capture_output=True,check=True)
        assert not any(s.encode() in logs.stdout+logs.stderr for s in protected if s),'Log secret leak'
    assert p1.sql('SELECT count(*) FROM execution_entity WHERE id IN (6,8);','n8n')=='2'
    public=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],capture_output=True,check=True).stdout
    for filename in filter(None,public.split(b'\0')):
        path=p1.ROOT/filename.decode()
        if path.is_file():assert not any(s.encode() in path.read_bytes() for s in protected if s),'Public file secret leak'
    for path in p4.PRIVATE.glob('*password'):
        assert subprocess.run(['git','check-ignore',str(path)],capture_output=True).returncode==0
    grants=p4.sql_p4("SELECT json_build_object('read_select',has_table_privilege('raa_p4_read','p4.chunks','SELECT'),'read_write',has_table_privilege('raa_p4_read','p4.chunks','INSERT,UPDATE,DELETE'),'ingest_select',has_table_privilege('raa_p4_ingest','p4.chunks','SELECT'),'ingest_insert',has_table_privilege('raa_p4_ingest','p4.chunks','INSERT'),'ingest_update_delete',has_table_privilege('raa_p4_ingest','p4.chunks','UPDATE,DELETE'),'read_only_setting',(SELECT rolconfig FROM pg_roles WHERE rolname='raa_p4_read'));")
    saved_schema=p1.sql("SELECT value->'parameters'->>'inputSchema' FROM workflow_entity,jsonb_array_elements(nodes::jsonb) WHERE id='p4-rag-core-v1' AND value->>'name'='Structured Output Parser';",'n8n')
    credentials=p1.sql("SELECT data FROM credentials_entity WHERE id IN ('p4-rag-read','p4-rag-ingest');",'n8n').splitlines()
    assert len(credentials)==2 and all(c and not c.startswith('{') for c in credentials)
    assert not any(s in c for c in credentials for s in protected if s)
    receipt={'executions':evidence,'database':json.loads(facts),'grants':json.loads(grants),'native_parser_schema_expression':saved_schema,'encrypted_credentials':True,
             'RAM':stats,'OOM':False,'history_logs_public_files_secret_scan':'PASS','old_executions_retained':True}
    if final:
        import p4_workflows as workflows
        accepted=[e for e in evidence if e.get('content_source_validation')=='PASS']
        assert set(workflows.QUESTIONS).issubset({e['question'] for e in accepted}),'Three real final RAG scenarios required'
        combined=next(e for e in accepted if e['question']==workflows.QUESTIONS[2])
        assert len(combined['citations'])>=2 and len(combined['source_ids'])>=2,'Multi-document answer required'
        live=json.loads(p1.sql("SELECT nodes::text FROM workflow_entity WHERE id='p4-rag-core-v1';",'n8n'))
        expected=workflows.workflows()[2]['nodes']
        by_name={n['name']:n for n in live}
        assert len(by_name)==10
        for n in expected:
            assert all(by_name[n['name']]['parameters'].get(k)==v for k,v in n['parameters'].items())
        assert by_name['AI Agent']['maxTries']==2 and by_name['AI Agent']['retryOnFail']
        receipt['status']='PASS'
        receipt['acceptance_execution_ids']=[e['id'] for e in accepted]
        receipt['answer_mode']='Model-selected schema-constrained policy summaries; exact retrieved quotations generated programmatically'
    (p1.ROOT/'evidence/p4_rag_runtime.json').write_text(json.dumps(receipt,indent=2)+'\n')
    summary={k:v for k,v in receipt.items() if k!='executions'}
    summary['executions']=[{k:v for k,v in e.items() if k not in ('retrieved_chunks','tool_calls','agent_output','quotes')} for e in evidence]
    for s,e in zip(summary['executions'],evidence):
        if 'agent_output' in e:s['agent_output']=e['agent_output']['output'];s['tool_observations']=[step['observation'] for step in e['agent_output'].get('intermediateSteps',[])]
    summary['executions']=[e for e in summary['executions'] if e['id']>=79]
    print(json.dumps(summary))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--final',action='store_true')
    main(parser.parse_args().final)
