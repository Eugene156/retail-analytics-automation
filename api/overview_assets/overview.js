/* Local navigation only. No API calls, credentials, storage or execution actions. */
'use strict';
const toggle = document.querySelector('.nav-toggle');
const navigation = document.querySelector('#navigation');
const mobile = window.matchMedia('(max-width: 850px)');
function closeNavigation() {
  navigation.classList.remove('is-open');
  toggle.setAttribute('aria-expanded', 'false');
}
toggle.addEventListener('click', () => {
  const open = !navigation.classList.contains('is-open');
  navigation.classList.toggle('is-open', open);
  toggle.setAttribute('aria-expanded', String(open));
  if (open) navigation.querySelector('a').focus();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && navigation.classList.contains('is-open')) {
    closeNavigation();
    toggle.focus();
  }
});
document.addEventListener('click', event => {
  if (mobile.matches && !navigation.contains(event.target) && !toggle.contains(event.target)) closeNavigation();
});
mobile.addEventListener('change', closeNavigation);

// F3: local historical evidence only. No transport or execution capability.
const agentCases = JSON.parse(document.querySelector('#agent-evidence').textContent);
const scenarioButtons = [...document.querySelectorAll('[data-scenario]')];
function showScenario(index) {
 const item = agentCases[index];
 scenarioButtons.forEach((button,i) => button.setAttribute('aria-pressed',String(i === index)));
 document.querySelector('#agent-provenance').textContent = `Historical execution #${item.execution_id} · ${item.executed_at} · Verified PASS`;
 document.querySelector('#agent-question').textContent = item.question;
 document.querySelector('#agent-answer').textContent = item.validated_answer;
 document.querySelector('#agent-origin').textContent = item.answer_origin;
 document.querySelector('#agent-model').textContent = item.model_response;
 const tools = document.querySelector('#agent-tools'); tools.replaceChildren();
 item.tool_calls.forEach(call => {
  const heading = document.createElement('h3'); heading.textContent = call.tool;
  const pre = document.createElement('pre');
  let result = call.result;
  if(typeof result === 'string') { try { result = JSON.parse(result); } catch (_) { /* Preserve non-JSON tool text. */ } }
  pre.textContent = JSON.stringify({input:call.input,result},null,2);
  const details=document.createElement('details'), summary=document.createElement('summary');
  summary.textContent='Saved tool request / response';details.append(summary,pre);
  tools.append(heading,details);
 });
}
scenarioButtons.forEach((button,index) => button.addEventListener('click',()=>showScenario(index)));
function showPage() {
 const active = location.hash === '#ai-agent';
 const mcp = location.hash === '#mcp-analytics';
 const knowledge = location.hash === '#knowledge-assistant';
 const engineering = location.hash === '#api-ci';
 document.querySelector('#main').hidden = active || mcp || knowledge || engineering;
 document.querySelector('#api-ci').hidden = !engineering;
 document.querySelector('#knowledge-assistant').hidden = !knowledge;
 document.querySelector('#mcp-analytics').hidden = !mcp;
 document.querySelector('#ai-agent').hidden = !active;
 document.querySelector('.breadcrumb strong').textContent = active ? 'AI Agent' : mcp ? 'MCP Analytics' : knowledge ? 'Knowledge Assistant' : engineering ? 'API & CI' : 'Overview';
 document.querySelector('.skip-link').setAttribute('href',active ? '#ai-agent' : mcp ? '#mcp-analytics' : knowledge ? '#knowledge-assistant' : engineering ? '#api-ci' : '#main');
 document.title = (active ? 'AI Agent' : mcp ? 'MCP Analytics' : knowledge ? 'Knowledge Assistant' : engineering ? 'API & CI' : 'Overview') + ' · Retail Analytics Automation';
 for (const link of navigation.querySelectorAll('a.nav-item')) {
  const current = active ? link.id === 'agent-nav' : mcp ? link.id === 'mcp-nav' : knowledge ? link.id === 'knowledge-nav' : engineering ? link.id === 'engineering-nav' : link.getAttribute('href') === '/overview';
  link.classList.toggle('active',current);
  if(current) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current');
 }
 closeNavigation();
}
window.addEventListener('hashchange',showPage);
showScenario(0); showPage();

// F4: safe presentation of stored MCP observations; no network or dispatch.
const mcpCases = JSON.parse(document.querySelector('#mcp-evidence').textContent);
const mcpButtons = [...document.querySelectorAll('[data-mcp-scenario]')];
function showMcpScenario(index) {
 const item=mcpCases[index];
 mcpButtons.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));
 document.querySelector('#mcp-provenance').textContent=`Historical P3 execution #${item.execution_id} · ${item.executed_at} · ${item.status}`;
 document.querySelector('#mcp-question').textContent=item.question;
 document.querySelector('#mcp-answer').textContent=item.answer;
 document.querySelector('#mcp-answer-origin').textContent=item.answer_origin === 'actual-tool-facts' ? 'Deterministic answer assembled from verified MCP facts; model tool selection shown separately.' : item.answer_origin;
 document.querySelector('#mcp-model').textContent=item.model_output;
 const metrics=document.querySelector('#mcp-metrics'); metrics.replaceChildren();
 const calls=document.querySelector('#mcp-calls'); calls.replaceChildren();
 function metric(label,value,source) {
  if(value===undefined) return;
  const box=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd'),small=document.createElement('small');
  dt.textContent=label;dd.textContent=String(value);small.textContent=source;
  box.append(dt,dd,small);metrics.append(box);
 }
 item.calls.forEach(call=>{
  const a=call.analytics;
  if(a.kpis) {
   for(const [label,key] of [['Sale rows','sale_rows'],['Net recorded sales (GBP)','net_recorded_sales_gbp'],['Gross sales (GBP)','sales_value_gbp'],['Cancellation rows','cancellation_rows'],['Cancellation magnitude (GBP)','cancellation_magnitude_gbp']]) metric(label,a.kpis[key],call.mcp_tool);
  }
  if(a.quality) {metric('Quality findings',a.quality.finding_rows,call.mcp_tool);metric('Missing customer sale rows',a.missing_customer_sale_rows,call.mcp_tool);}
  const h=document.createElement('h3');h.textContent=call.mcp_tool;
  const p=document.createElement('p');p.textContent=`n8n tool: ${call.client_tool} · Access: ${a.access}`;
  const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
  summary.textContent='Saved MCP request / response payload';
  pre.textContent=JSON.stringify({tool:call.mcp_tool,input:call.input,response:call.raw_response},null,2);
  details.append(summary,pre);calls.append(h,p,details);
 });
 // Return long payloads to their collapsed state after every scenario switch.
 document.querySelectorAll('#mcp-analytics details').forEach(detail=>detail.open=false);
}
mcpButtons.forEach((button,index)=>button.addEventListener('click',()=>showMcpScenario(index)));
showMcpScenario(0);

// F5: display immutable historical retrieval evidence; never call a backend.
const ragCases=JSON.parse(document.querySelector('#rag-evidence').textContent);
const ragButtons=[...document.querySelectorAll('[data-rag-scenario]')];
function showRagScenario(index) {
 const item=ragCases[index];
 ragButtons.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));
 document.querySelector('#rag-provenance').textContent=`Historical P4 execution #${item.execution_id} · ${item.executed_at} · ${item.status}`;
 document.querySelector('#rag-question').textContent=item.question;
 document.querySelector('#rag-answer').textContent=item.answer;
 document.querySelector('#rag-used-sources').textContent='Answer source IDs: '+item.source_ids.join(', ');
 const sources=document.querySelector('#rag-citations');sources.replaceChildren();
 item.quotes.forEach(quote=>{
  const article=document.createElement('article'),h=document.createElement('h3'),p=document.createElement('p'),excerpt=document.createElement('blockquote'),a=document.createElement('a');
  h.textContent=quote.source_path.split('/').pop();p.textContent=`Source: ${quote.source_id} · Chunk: ${quote.chunk_id}`;
  renderSourceExcerpt(excerpt,quote.text);a.textContent='Citation: '+quote.chunk_id+' · execution #'+item.execution_id;
  a.href=quote.url;article.append(h,p,excerpt,a);
  if(quote.text.split('\n').some(line=>line.trim().startsWith('|'))) {
   const exact=document.createElement('details'),label=document.createElement('summary'),raw=document.createElement('pre');
   label.textContent='Exact source excerpt';raw.textContent=quote.text;exact.append(label,raw);article.append(exact);
  }
  sources.append(article);
 });
 const docs=document.querySelector('#rag-documents');docs.replaceChildren();
 const paths=[...new Set(item.retrieved_chunks.map(c=>c.source_path))];
 paths.forEach(path=>{const li=document.createElement('li');li.textContent=path;docs.append(li);});
 const models=[...new Set(item.retrieved_chunks.map(c=>c.embedding_model))];
 document.querySelector('#rag-retrieval').textContent=`Saved pgvector similarity search: ${item.retrieved_chunks.length} chunks · ${item.embedding_dimensions} dimensions · Ollama embeddings: ${models.join(', ')}. Excerpts above are the cited support; the raw panel includes all retrieved context.`;
 document.querySelector('#rag-raw').textContent=JSON.stringify({retrieved_chunks:item.retrieved_chunks,citations:item.citations,model_response:item.model_response},null,2);
 document.querySelectorAll('#knowledge-assistant details').forEach(d=>d.open=false);
}
ragButtons.forEach((button,index)=>button.addEventListener('click',()=>showRagScenario(index)));
showRagScenario(0);

// F6: source-backed documentation only; downloads remain local Blob artifacts.
const engineeringData=JSON.parse(document.querySelector('#engineering-evidence').textContent);
const engineeringButtons=[...document.querySelectorAll('[data-engineering-section]')];
function showEngineeringSection(key) {
 engineeringButtons.forEach(button=>{
  const active=button.dataset.engineeringSection===key;
  button.setAttribute('aria-pressed',String(active));
  document.querySelector('#engineering-'+button.dataset.engineeringSection).hidden=!active;
 });
 document.querySelector('#engineering-status').textContent='Viewing: '+engineeringButtons.find(b=>b.dataset.engineeringSection===key).textContent+' · Documentation only; no requests or tests run by selection.';
 document.querySelectorAll('#api-ci details').forEach(d=>d.open=false);
}
engineeringButtons.forEach(button=>button.addEventListener('click',()=>showEngineeringSection(button.dataset.engineeringSection)));
const endpoints=document.querySelector('#engineering-endpoints');
Object.entries(engineeringData.spec.paths).forEach(([path,methods])=>Object.entries(methods).forEach(([method,operation])=>{
 if(!['get','post'].includes(method))return;
 const box=document.createElement('article'),h=document.createElement('h3'),p=document.createElement('p'),pre=document.createElement('pre');
 h.textContent=method.toUpperCase()+' '+path;p.textContent=operation.summary;
 pre.textContent='HTTP responses: '+Object.keys(operation.responses).join(', ');
 box.append(h,p,pre);endpoints.append(box);
}));
const calculation=engineeringData.spec.paths['/api/v1/calculations/comparison'].post;
document.querySelector('#engineering-contract').textContent=JSON.stringify({note:'OpenAPI documentation contract; not a saved HTTP response',request:calculation.requestBody,schema:engineeringData.spec.components.schemas.CalculationRequest,responses:calculation.responses},null,2);
document.querySelector('#engineering-tests').textContent=engineeringData.ci.split('python -m pytest -q ')[1].trim();
document.querySelector('#engineering-yaml').textContent=engineeringData.ci;
document.querySelector('#engineering-requirements').textContent=engineeringData.ci_requirements;
Object.entries(engineeringData.artifacts).forEach(([name,content])=>{
 const a=document.createElement('a');a.textContent='Download '+name;a.download=name;
 a.href=URL.createObjectURL(new Blob([content],{type:name.endsWith('.json')?'application/json':'text/markdown'}));
 document.querySelector('#engineering-downloads').append(a);
});
showEngineeringSection('api');

// Presentation only. Original excerpt bytes remain in the exact-source disclosure.
function renderSourceExcerpt(container,text) {
 for(const line of text.split('\n')) {
  if(!line.trim()) continue;
  if(line.trim().startsWith('|')) {
   const cells=line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell=>cell.trim());
   const row=document.createElement('div');row.className='source-term';
   cells.forEach((cell,index)=>{const part=document.createElement(index===0?'strong':'span');part.textContent=cell;row.append(part);});
   container.append(row);
  } else {const p=document.createElement('p');p.textContent=line;container.append(p);}
 }
}
