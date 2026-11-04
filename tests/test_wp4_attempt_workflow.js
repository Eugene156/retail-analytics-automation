// Exact exported Code policies in a VM. Separate from actual HTTP/n8n evidence.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const w=JSON.parse(fs.readFileSync(0,'utf8')),nodes=Object.fromEntries(w.nodes.map(n=>[n.name,n]));
const p={action_id:'00000000-0000-0000-0000-000000000001',case_id:'00000000-0000-0000-0000-000000000002',
 request_sha256:'a'.repeat(64),report_sha256:'b'.repeat(64),acceptance_key:'business-key-123'};
function run(name,value,id='100',linked){return vm.runInNewContext('(function(){'+nodes[name].parameters.jsCode+'})()',
 {$input:{first:()=>({json:value})},$execution:{id},$:()=>({item:{json:linked}}),Date})[0].json;}
const copy=x=>JSON.parse(JSON.stringify(x));
const initial=run('Validate approved action',p);
assert.throws(()=>run('Validate approved action',{...p,action_id:null}));
assert.throws(()=>run('Validate approved action',p,'0'));
function dispatch(v){return run('Dispatch bounded operation',v);}
function response(body,status=200,headers={}){return {statusCode:status,body_text:JSON.stringify(body),headers};}
function evaluate(r,ctx){return run('Evaluate attempt result',r,'100',ctx);}
function state(n=0,kind='pending'){
 const b={contract_version:'portal-attempt-api-state-v1',reservation_acknowledged:false,acceptance_permitted:false,
 worker:{contract_version:'portal-worker-state-v1',...p,request_id:'00000000-0000-0000-0000-000000000003',key_bound:false,revision:1,target_id:initial.target_id,
 status:'pending',created_at:'2026-10-06T00:00:00Z',expires_at:'2026-10-07T00:00:00Z',observed_at:'2026-10-06T01:00:00Z',receipt:null},
 ledger:{state:kind,attempt_count:n,max_attempts:3,event_no:n,acceptance_key:p.acceptance_key,observed_at:'2026-10-06T01:00:00Z',reconciliation_required:n>0,
 attempt_id:n?'00000000-0000-0000-0000-000000000004':null,attempt_key:n?'n8n_100_slot_'+n:null,execution_id:n?'100':null,lease_expires_at:n?'2026-10-06T01:00:30Z':null,last_kind:n?'reserved':null}};
 if(['retryable','dead_letter','exhausted'].includes(kind)){b.ledger.last_kind='reconciled';b.ledger.reconciliation_required=false;}
 if(kind==='unknown')b.ledger.last_kind='reported';
 return b;
}
let ctx=dispatch(initial),res=evaluate(response(state()),ctx);
assert.equal(res.next,'reserve');assert.equal(res.reserve_key,'n8n_100_slot_1');
ctx=dispatch(res);const live=state(1,'reserved');live.reservation_acknowledged=live.acceptance_permitted=true;
res=evaluate(response(live),ctx);assert.equal(res.next,'state');assert.ok(res.grant);
ctx=dispatch(res);res=evaluate(response(state(1,'reserved')),ctx);assert.equal(res.next,'accept');
const accept=dispatch(res);assert.equal(accept.body.attempt_id,live.ledger.attempt_id);
res=evaluate(response({},503,{'Retry-After':'1'}),accept);assert.equal(res.next,'state');assert.equal(res.report_outcome,'uncertain');
ctx=dispatch(res);res=evaluate(response(state(1,'reserved')),ctx);assert.equal(res.next,'report');assert.equal(res.body.outcome,'uncertain');
ctx=dispatch(res);res=evaluate(response(state(1,'unknown')),ctx);ctx=dispatch(res);
res=evaluate(response(state(1,'unknown')),ctx);assert.equal(res.next,'reconcile');
ctx=dispatch(res);res=evaluate(response(state(1,'retryable')),ctx);ctx=dispatch(res);
res=evaluate(response(state(1,'retryable')),ctx);assert.equal(res.next,'reserve');assert.equal(res.reserve_key,'n8n_100_slot_2');
const reserve=dispatch(evaluate(response(state()),dispatch(initial)));
const lost=evaluate(response({},503,{'Retry-After':'1'}),reserve);
const replay=evaluate(response(state(1,'reserved')),dispatch(lost));assert.equal(replay.next,'reserve');assert.equal(replay.reserve_key,reserve.reserve_key);
const ungranted=evaluate(response(state(1,'reserved')),dispatch({...lost,grant:null}));assert.notEqual(ungranted.next,'accept');
const foreign=state(1,'reserved');foreign.ledger.execution_id='101';foreign.ledger.attempt_key='n8n_101_slot_1';
const wait=evaluate(response(foreign),dispatch(initial));assert.equal(wait.next,'state');assert.equal(wait.wait_seconds,31);assert.equal(wait.grant,null);
const wrongGrant=copy(live);wrongGrant.ledger.execution_id='101';assert.equal(evaluate(response(wrongGrant),reserve).continue,false);
const unexpectedGrant=copy(live);assert.equal(evaluate(response(unexpectedGrant),dispatch(initial)).continue,false);
assert.throws(()=>run('Evaluate attempt result',response(state()),'101',dispatch(initial)),/Stale execution/);
assert.throws(()=>dispatch({...initial,next:'recover'}));
assert.throws(()=>dispatch({...initial,wire_calls:32}));
assert.throws(()=>dispatch({...initial,next:'accept',body:{attempt_id:live.ledger.attempt_id,execution_id:'100'}}));
for(const kind of ['dead_letter','exhausted'])assert.equal(evaluate(response(state(kind==='exhausted'?3:1,kind)),dispatch(initial)).continue,false);
const expired=state();expired.worker.status=expired.ledger.state='expired';expired.worker.observed_at=expired.ledger.observed_at=expired.worker.expires_at;
assert.equal(evaluate(response(expired),dispatch(initial)).reason,'terminal_expired');
for(const field of ['action_id','case_id','acceptance_key','request_sha256','report_sha256','target_id']){
 const b=state();b.worker[field]='tampered';assert.equal(evaluate(response(b),dispatch(initial)).continue,false);
}
for(const [field,bad] of [['max_attempts',4],['attempt_count',4],['event_no',33],['acceptance_key','changed-key'],['reconciliation_required','false']]){
 const b=state();b.ledger[field]=bad;assert.equal(evaluate(response(b),dispatch(initial)).continue,false);
}
const success=state(1,'published');success.ledger.last_kind='accepted';success.ledger.reconciliation_required=false;
success.worker.status='published';success.worker.key_bound=true;
success.worker.receipt={action_id:p.action_id,case_id:p.case_id,request_id:success.worker.request_id,request_sha256:p.request_sha256,content_sha256:p.report_sha256,revision:1,content_bytes:100,publication_semantics:'guarded-server-acceptance-v1',publication:{publication_id:'00000000-0000-0000-0000-000000000005',target_id:initial.target_id,accepted_at:'2026-10-06T00:30:00Z'}};
assert.equal(evaluate(response(success),accept).published,false);
const final=evaluate(response(success),dispatch(initial));assert.equal(final.published,true);
assert.equal(run('Verified committed publication',final).automatic_budget_reset,false);
assert.throws(()=>run('Verified committed publication',{...final,operation:'accept'}));
success.worker.observed_at=success.ledger.observed_at='2026-10-08T00:00:00Z';assert.equal(evaluate(response(success),dispatch(initial)).published,true);
success.worker.receipt.content_sha256='c'.repeat(64);assert.equal(evaluate(response(success),dispatch(initial)).published,false);
assert.equal(evaluate(response({},503,{'Retry-After':'12'}),dispatch(initial)).wait_seconds,12);
assert.equal(evaluate(response({},503,{'Retry-After':'0'}),dispatch(initial)).wait_seconds,1);
assert.equal(evaluate(response({},503,{'Retry-After':'61'}),dispatch(initial)).continue,false);
assert.equal(evaluate(response({},503,{'Retry-After':'9'.repeat(400)}),dispatch(initial)).continue,false);
assert.equal(evaluate(response({},503,{'Retry-After':'garbage'}),dispatch(initial)).wait_seconds,5);
assert.equal(evaluate(response({},401),dispatch(initial)).continue,false);
assert.equal(evaluate(response({},401),accept).report_outcome,'permanent');
assert.equal(evaluate({error:{message:'not logged'}},dispatch(initial)).next,'state');
assert.equal(w.active,false);assert.deepEqual(w.pinData,{});assert.equal(nodes['Call fixed attempt API'].retryOnFail,false);
assert.equal(w.connections['Bounded backoff'].main[0][0].node,'Dispatch bounded operation');
assert.ok(Object.values(nodes).every(n=>!n.credentials));
console.log('PASS|exact-attempt-workflow-VM|committed-grant|same-slot-ack-replay|foreign-lease|three-durable-slots|32-wire-bound|no-operator');
