// Execute the exact exported Code-node policy in a pure VM; no live HTTP claim.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const workflow = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = Object.fromEntries(workflow.nodes.map(node => [node.name, node]));
function execute(name, input, runIndex = 0, histories = {}, binary = {}) {
  const context = {
    $input: {first: () => ({json: input, binary})}, $runIndex: runIndex, $execution: {id: 'unit-execution'},
    $: node => ({first: (branch = 0, run = 0) => {
      if (!histories[node]?.[run]) throw new Error('Missing test run');
      return {json: histories[node][run]};
    }})
  };
  return new vm.Script(`(function(){${nodes[name].parameters.jsCode}\n})()`).runInNewContext(context)[0].json;
}
const plan = execute('Prepare request', {});
const identity = {contract_version: 'report-request-v1', policy_version: 'v1',
  report_schema_version: 'deterministic-comparison-report-v1',
  source_file_sha256: plan.request.source_file_sha256,
  source_time_interpretation: plan.request.source_time_interpretation, ...plan.expected_source_window};
const cid = '00000000-0000-0000-0000-000000000003';
const body = {case_id: cid, state: 'awaiting_approval', revision: 1,
  schema_version: 'deterministic-comparison-report-v1', payload_sha256: 'a'.repeat(64),
  request: identity, approved: false, published: false, audit_events: [{event_id: 'one'}, {event_id: 'two'}]};
const histories = {'Prepare request': [plan]};
const reply = (statusCode, value = body, headers = {}) => ({statusCode, body_text: JSON.stringify(value), headers});
const evaluate = (reply, index = 0, extra = {}) => execute('Evaluate request', reply, index, {...histories, ...extra});

for (const node of workflow.nodes) {
  assert.equal(node.credentials, undefined);
  if (node.type === 'n8n-nodes-base.httpRequest') {
    assert.equal(node.parameters.options.response.response.responseFormat,
                 node.name === 'Read unapproved draft' ? 'file' : 'text');
    assert.equal(node.parameters.options.redirect.redirect.followRedirects, false);
    assert.equal(node.retryOnFail, false);
  }
}
assert.equal(workflow.active, false);
assert.equal(nodes['Submit request'].parameters.url, 'http://raa-wp2-api:8000/api/v1/report-requests');
const ready = evaluate(reply(200));
assert.equal(ready.ready, true);
assert.equal(ready.case_id, cid);
for (const status of [401, 403, 404, 409, 422, 500]) {
  const value = evaluate(reply(status, {secret: 'not-for-output'}));
  assert.equal(value.retry, false);
  assert.equal(value.ready, false);
  assert(!JSON.stringify(value).includes('not-for-output'));
}
for (const status of [429, 503, 504]) {
  assert.equal(evaluate(reply(status)).wait_seconds, 5);
  assert.equal(evaluate(reply(status), 1).wait_seconds, 10);
  assert.equal(evaluate(reply(status), 2).reason, 'retry_exhausted_manual_recovery');
}
const pending = {...body, state: 'received', revision: null};
assert.equal(evaluate(reply(202, pending)).retry, true);
assert.equal(evaluate(reply(202, body)).reason, 'invalid_pending_case');
assert.equal(evaluate(reply(503, {}, {'Retry-After': '12'})).wait_seconds, 12);
assert.equal(evaluate(reply(503, {}, {'retry-after': '0'})).wait_seconds, 1);
assert.equal(evaluate(reply(503, {}, {'retry-after': 'garbage'})).wait_seconds, 5);
assert.equal(evaluate(reply(503, {}, {'retry-after': '61'})).reason, 'retry_after_exceeds_local_bound');
assert.equal(evaluate(reply(503, {}, {'retry-after': '9'.repeat(500)})).retry, false);
assert.equal(evaluate(reply(503, {}, {'retry-after': 'Wed, 01 Jan 2099 00:00:00 GMT'})).retry, false);
assert.equal(evaluate({error: {message: 'private'}}).reason, 'transport_failure_manual_recovery');
assert.equal(evaluate({statusCode: 200, body_text: '{bad'}).reason, 'invalid_case_response');
for (const changed of [{...body, published: true}, {...body, approved: true},
                        {...body, request: {...identity, source_file_sha256: 'wrong'}},
                        {...body, revision: 2}, {...body, payload_sha256: 'wrong'}]) {
  assert.equal(evaluate(reply(200, changed)).ready, false);
}
assert.equal(evaluate(reply(200), 1, {'Evaluate request': [{case_id: 'different'}]}).reason, 'case_identity_mismatch');
const stored = execute('Validate stored case', reply(200), 0, {...histories, 'Evaluate request': [ready]});
assert.equal(stored.case_id, cid);
assert.equal(stored.request_attempts, 1);
const exact = '{"ratio":0.73293010234875627641,"money":1349.45}';
const binary = {draft_bytes: {data: Buffer.from(exact).toString('base64')}};
const preserved = execute('Preserve exact draft bytes', {statusCode: 200,
  headers: {'x-report-status': 'unapproved-draft', 'x-source-time-interpretation': 'Europe/London-assumed',
            'content-length': String(Buffer.byteLength(exact))}},
  0, {'Validate stored case': [stored]}, binary);
assert.equal(preserved.draft_text, undefined);
assert.equal(nodes['SHA256 exact draft bytes'].parameters.binaryData, true);
assert.equal(nodes['SHA256 exact draft bytes'].parameters.binaryPropertyName, 'draft_bytes');
assert.throws(() => execute('Preserve exact draft bytes', {statusCode: 200, headers: {
  'x-report-status': 'unapproved-draft', 'x-source-time-interpretation': 'Europe/London-assumed',
  'content-length': '65537'}}, 0, {'Validate stored case': [stored]}, binary), /Invalid unapproved/);
assert.throws(() => execute('Preserve exact draft bytes', {statusCode: 200, headers: {
  'x-report-status': 'unapproved-draft', 'x-source-time-interpretation': 'Europe/London-assumed',
  'content-length': '50'}}, 0, {'Validate stored case': [stored]}), /Invalid unapproved/);
assert.throws(() => execute('Verified unapproved draft', {...preserved, actual_payload_sha256: 'b'.repeat(64)}), /hash mismatch/);
assert.equal(execute('Verified unapproved draft', {...preserved, actual_payload_sha256: 'a'.repeat(64)}).publication, 'not_enabled');
console.log('PASS|exact-export-policy-VM|fixed-targets|sanitized|three-attempt-bound|Retry-After|permanent-errors|identity|draft-bytes|hash-rejection');
