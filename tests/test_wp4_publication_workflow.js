// Exact exported Code-node policy; no live n8n/HTTP evidence.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const w=JSON.parse(fs.readFileSync(0,'utf8')),nodes=Object.fromEntries(w.nodes.map(n=>[n.name,n]));
const p={action_id:'00000000-0000-0000-0000-000000000001',case_id:'00000000-0000-0000-0000-000000000002',
 request_sha256:'a'.repeat(64),report_sha256:'b'.repeat(64),acceptance_key:'stable-test-key'};
function run(name,input,index=0,hist={}){
 const context={$input:{first:()=>({json:input})},$runIndex:index,$execution:{id:'test-execution'},
  $:n=>({first:(_,i=0)=>({json:hist[n][i]}),item:{json:(hist[n]||[]).at(-1)}})};
 return new vm.Script(`(function(){${nodes[name].parameters.jsCode}\n})()`).runInNewContext(context)[0].json;
}
const plan=run('Validate approved action',p),hist={'Validate approved action':[plan]};
const state={contract_version:'portal-worker-state-v1',...plan,revision:1,key_bound:false,
 request_id:'00000000-0000-0000-0000-000000000003',status:'pending',receipt:null,
 created_at:'2026-10-06T00:00:00Z',expires_at:'2026-10-07T00:00:00Z',observed_at:'2026-10-06T01:00:00Z'};
const response=(statusCode,body=state,headers={})=>({statusCode,body_text:JSON.stringify(body),headers});
const evaluate=(r,index=0)=>run('Evaluate state',r,index,hist);
assert.equal(w.active,false);assert.deepEqual(w.pinData,{});
assert.throws(()=>run('Validate approved action',{}),/Explicit approved/);
assert.throws(()=>run('Validate approved action',{...p,target:'https://outside.invalid'}),/Explicit approved/);
for(const n of w.nodes){assert.equal(n.credentials,undefined);
 if(n.type==='n8n-nodes-base.httpRequest'){
  assert.equal(n.retryOnFail,false);assert.equal(n.parameters.options.redirect.redirect.followRedirects,false);
  assert(n.parameters.url.includes('http://raa-wp4-portal-test:8000/api/v3/portal-actions/'));
 }
 if(n.type==='n8n-nodes-base.code')assert(!/require\(|fetch\(|process\.|\$env/.test(n.parameters.jsCode));
}
for(let cycle=0;cycle<3;cycle++)assert.equal(evaluate(response(200),cycle).post_allowed,true);
assert.equal(evaluate(response(200),3).post_allowed,false);
for(const status of ['expired','superseded'])assert.equal(evaluate(response(200,{...state,status})).post_allowed,false);
for(const s of [401,403,404,409,422,500]){
 const result=evaluate(response(s,{secret:'must-not-be-reflected'}));assert.equal(result.retry,false);
 assert(!JSON.stringify(result).includes('must-not-be-reflected'));
}
for(const s of [429,503,504]){
 assert.equal(evaluate(response(s)).retry,true);assert.equal(evaluate(response(s),3).retry,false);
}
assert.equal(evaluate({error:{message:'private'}}).retry,true);
assert.equal(evaluate(response(503,{}, {'Retry-After':'12'})).wait_seconds,12);
assert.equal(evaluate(response(503,{}, {'Retry-After':'0'})).wait_seconds,1);
assert.equal(evaluate(response(503,{}, {'Retry-After':'61'})).retry,false);
assert.equal(evaluate(response(503,{}, {'Retry-After':'9'.repeat(400)})).retry,false);
assert.equal(evaluate(response(503,{}, {'Retry-After':'garbage'})).wait_seconds,5);
assert.equal(evaluate({statusCode:200,body_text:'{bad'}).post_allowed,false);
for(const change of [{action_id:p.case_id},{request_sha256:'c'.repeat(64)},{target_id:'legacy'},{revision:2},{acceptance_key:'changed-key'},{expires_at:'2026-10-08T00:00:00Z'}])
 assert.equal(evaluate(response(200,{...state,...change})).post_allowed,false);
const published={...state,status:'published',key_bound:true,receipt:{action_id:p.action_id,case_id:p.case_id,
 request_id:state.request_id,request_sha256:p.request_sha256,content_sha256:p.report_sha256,content_bytes:100,
 revision:1,publication_semantics:'guarded-server-acceptance-v1',publication:{publication_id:'00000000-0000-0000-0000-000000000004',target_id:plan.target_id,accepted_at:'2026-10-06T02:00:00Z'}}};
const result=evaluate(response(200,published),3);assert.equal(result.published,true);
const late={...published,observed_at:'2026-10-08T00:00:00Z'};
assert.equal(evaluate(response(200,late)).published,true); // Timely committed acceptance remains readable later.
assert.equal(evaluate(response(200,{...published,key_bound:false})).published,false);
assert.equal(evaluate(response(200,{...published,receipt:{...published.receipt,content_sha256:'c'.repeat(64)}})).published,false);
const evaluated=evaluate(response(200),1);
for(const s of [200,429,503,504,null]){
 const r=run('Evaluate acceptance',s===null?{error:{message:'private'}}:response(s,{}, {'Retry-After':'1'}),0,
  {'Evaluate state':[evaluated]});assert.equal(r.published,false);assert.equal(r.retry,true);assert.equal(r.cycle,2);
}
assert.equal(run('Evaluate acceptance',response(401),0,{'Evaluate state':[evaluated]}).retry,false);
assert.equal(run('Verified committed publication',result).automatic_approval,false);
assert.throws(()=>run('Verified committed publication',evaluated),/not reconciled/);
assert.equal(w.connections['Bounded backoff'].main[0][0].node,'Read state');
console.log('PASS|exact-publication-workflow-VM|fixed-target|reconcile-before-write|three-POST-bound|same-key|expiry|Retry-After|no-secrets');
