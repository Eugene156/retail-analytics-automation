"""Targeted tests of policy meaning, source binding and generated exact quotes."""
import json
import subprocess
from pathlib import Path
import p4_workflows as w

NODE=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'


def main():
    chunks=[]
    for doc in w.documents():
        start=i=0
        while start<len(doc['text']):
            end=min(start+450,len(doc['text']))
            if end<len(doc['text']):
                boundary=doc['text'].rfind(' ',0,end+1)
                if boundary>start+250:end=boundary
            chunks.append(dict(doc,chunk_id=f"{doc['source_id']}#{i}",text=doc['text'][start:end].strip()))
            i+=1
            if end==len(doc['text']):break
            start=end-64
    answers={r['id']:r['answer'] for r in w.ANSWER_RULES}
    cases=[]
    for question,ids,sources in [(w.QUESTIONS[0],['net','adjustments'],['kpi-dictionary']),
                                (w.QUESTIONS[1],['cancellation','physical'],['kpi-dictionary','data-contract']),
                                (w.QUESTIONS[2],['net','adjustments','missing','coverage'],['kpi-dictionary','data-contract'])]:
        retrieved=[c for c in chunks if c['chunk_id'] in (
            ['kpi-dictionary#0','data-contract#1','data-contract#0','kpi-dictionary#1'] if question==w.QUESTIONS[0] else
            ['kpi-dictionary#0','kpi-dictionary#1','data-contract#2','data-contract#1'] if question==w.QUESTIONS[1] else
            ['kpi-dictionary#1','data-contract#1','kpi-dictionary#2','kpi-dictionary#0'])]
        cases.append({'question':question,'matches':retrieved,'output':{'answer':[answers[i] for i in ids],'source_ids':sources},'pass':True})
    def reject(output,**kw):cases.append(dict(cases[2],output=output,**{'pass':False},**kw))
    reject({'answer':[answers['net']],'source_ids':['invented']})
    reject({'answer':['Missing customer IDs are excluded from sales.'],'source_ids':['data-contract']})
    reject({'answer':['No cancellations.'],'source_ids':['kpi-dictionary']})
    reject({'answer':['Profit is £9000.'],'source_ids':['kpi-dictionary']})
    reject({'answer':[answers['net']],'source_ids':['kpi-dictionary']})
    reject({'answer':[answers[i] for i in ['net','adjustments','missing','coverage']],'source_ids':['kpi-dictionary']})
    reject({'answer':[answers[i] for i in ['net','adjustments','missing','coverage']],'source_ids':['kpi-dictionary','data-contract']},matches=cases[2]['matches'][:2])
    reject({'answer':[w.INSUFFICIENT],'source_ids':[]})
    reject('not JSON')
    cases.append(dict(cases[2],question='What is the refund payment date?',output={'answer':[w.INSUFFICIENT],'source_ids':[]},**{'pass':True}))
    code='const guard=new Function("$json","$","$execution",'+json.dumps(w.answer_guard())+');\n'
    code+='const cases='+json.dumps(cases)+';\n'
    code+='const schemaFor=new Function("$",'+json.dumps(w.schema_builder())+');\n'
    code+='let schemaCount=0;for(const c of cases.filter(c=>c.pass)){const s=JSON.parse(schemaFor(name=>({first:()=>({json:name==="Semantic search"?{matches:c.matches}:{question:c.question}})})));if(s.properties.answer.minItems!==c.output.answer.length||s.properties.source_ids.minItems!==c.output.source_ids.length||c.output.answer.some(a=>!s.properties.answer.items.enum.includes(a)))throw new Error("Required schema coverage mismatch");schemaCount++;}console.log("PASS|"+schemaCount+" question-specific schemas");\n'
    code+='''let count=0;for(const c of cases){let out,ok=true,error;try{out=guard({output:c.output},name=>({first:()=>({json:name==='Semantic search'?{matches:c.matches}:{question:c.question}})}),{id:999});}catch(e){ok=false;error=e.message;}if(ok!==c.pass)throw new Error('Guard case failed '+count+' '+error);if(ok&&out[0].json.status==='PASS'){for(const z of out[0].json.quotes){if(!c.matches.some(m=>m.chunk_id===z.chunk_id&&m.text===z.text))throw new Error('Quote mismatch');}if(out[0].json.answer!==c.output.answer.join(' '))throw new Error('Model answer rewritten');}count++;}console.log('PASS|'+count+' semantic/source/schema/quote cases');'''
    result=subprocess.run([str(NODE)],input=code,text=True,capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr)
    print(result.stdout.strip())


if __name__=='__main__':main()
