'use strict';
(() => {
  const base = '/portal/f2';
  const create = document.querySelector('#create'), refresh = document.querySelector('#refresh');
  const next = document.querySelector('#new'), notice = document.querySelector('#notice');
  const details = document.querySelector('#details'), review = document.querySelector('#review');
  // IDs only; never session credentials, report payloads or signing material.
  let operation = sessionStorage.getItem('raa-f2-operation');
  let busy = false;
  function render(value) {
    const state = value.review?.status || value.result?.status || value.state;
    document.querySelector('main').dataset.state = state;
    details.replaceChildren();
    for (const [name, data] of Object.entries({Operation: value.operation_id, State: state,
      'Workflow execution': value.execution_id, 'Review state': value.review_status,
      'Request ID': value.result?.request_id, 'Case ID': value.result?.case_id,
      'Report SHA-256': value.review?.report_sha256 || value.result?.report_sha256,
      'Request SHA-256': value.review?.request_sha256, Target: value.review?.target})) {
      if (data == null) continue;
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = name; dd.textContent = data; details.append(dt, dd);
    }
    create.hidden = true; refresh.hidden = false;
    next.hidden = value.state !== 'CREATED'; review.hidden = !value.result;
    if (value.result) review.href = value.result.review_url;
    document.querySelector('#report').hidden = !value.review;
    document.querySelector('#preview').textContent = value.review?.report_text || '';
    const receipt = value.review?.publication || value.review?.decision_receipt;
    document.querySelector('#receipt').hidden = !receipt;
    document.querySelector('#receipt-text').textContent = receipt ? JSON.stringify(receipt, null, 2) : '';
    const steps = document.querySelectorAll('.f2-steps li');
    steps.forEach(step => step.removeAttribute('aria-current'));
    steps[!value.result ? 0 : ['PUBLISHED','REJECTED','APPROVED'].includes(state) ? 4 : 1].setAttribute('aria-current','step');
    notice.textContent = value.review ? 'Saved backend result: ' + state + '. Review state: ' + value.review_status + '.' :
      value.state === 'CREATED' ? 'Report created. Refresh to inspect its report and current review state.' :
      'Creation outcome is unresolved. Refresh or reconcile this operation; do not submit another request.';
  }
  async function request(path, options) {
    const response = await fetch(base + path, {credentials: 'same-origin', redirect: 'error', ...options});
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || 'State unavailable');
    render(value);
  }
  create.addEventListener('click', async () => {
    if (busy) return;
    busy = true; create.disabled = true;
    operation ||= crypto.randomUUID(); sessionStorage.setItem('raa-f2-operation', operation);
    notice.textContent = 'Creation submitted. Do not resubmit while the outcome is unresolved.';
    try { await request('/create', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({operation_id: operation, csrf: document.querySelector('meta[name="csrf-token"]').content})}); }
    catch (error) { notice.textContent = error.message + '. Keep this operation ID; do not resubmit.'; create.hidden = true; refresh.hidden = false; }
    finally { busy = false; }
  });
  refresh.addEventListener('click', () => request('/operations/' + operation).catch(e => {notice.textContent = e.message;}));
  next.addEventListener('click', () => { operation = null; sessionStorage.removeItem('raa-f2-operation');
    create.hidden = false; create.disabled = false; next.hidden = true; review.hidden = true;
    refresh.hidden = true; document.querySelector('#report').hidden = true; document.querySelector('#receipt').hidden = true;
    document.querySelector('main').removeAttribute('data-state'); details.replaceChildren(); notice.textContent = 'Ready for a new explicit request.'; });
  if (operation) { create.hidden = true; refresh.hidden = false;
    request('/operations/' + operation).catch(e => {notice.textContent = e.message + '. Retain the operation ID for reconciliation.';}); }
})();
