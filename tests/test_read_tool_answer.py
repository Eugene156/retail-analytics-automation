"""Run the actual exported JavaScript guards with varied synthetic tool facts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get('RAA_TEST_NODE') or shutil.which('node')


def fixture(mcp):
    names = ['get_sales_kpis', 'get_data_quality'] if mcp else ['Get_Sales_KPIs', 'Get_Data_Quality']
    common = {'schema_version': 'p2-read-tool-v1', 'access': 'read-only',
              'source_file_sha256': 'synthetic', 'period': {'source_file_sha256': 'synthetic'}}
    bodies = [dict(common, kpis={'sale_rows': 19, 'net_recorded_sales_gbp': '-12.34',
               'sales_value_gbp': '555.66', 'cancellation_rows': 17,
               'cancellation_magnitude_gbp': '568.00'}),
              dict(common, quality={'finding_rows': 3}, missing_customer_sale_rows=2)]
    steps = [{'action': {'tool': 'MCP_Client_Tool_' + name if mcp else name},
              'observation': json.dumps([{'structuredContent': body}] if mcp else [body])}
             for name, body in zip(names, bodies)]
    return {'output': json.dumps({'source_tools': names}), 'intermediateSteps': steps}


def run_guard(value, mcp, legacy_only=False):
    assert NODE, 'Node is required to execute the actual workflow guard'
    path = ROOT / 'workflows' / ('p3_mcp_agent_core.json' if mcp else 'p2_read_agent_core.json')
    script = "const fs=require('fs');const x=JSON.parse(fs.readFileSync(0,'utf8'));try{console.log(JSON.stringify(new Function('$json',x.code)(x.input)))}catch(e){console.log(JSON.stringify({error:e.message}));process.exitCode=1}"
    code = next(n['parameters']['jsCode'] for n in json.loads(path.read_text())['nodes']
                if n['name'] == 'Validate tool evidence')
    if legacy_only:
        # Exercise retained numeric guard independently of the new renderer.
        code = re.sub(r'const r=renderReadToolAnswer\(\$json,[^\n]+\);', 'const r=$json;', code, count=1)
    completed = subprocess.run([NODE, '-e', script], input=json.dumps({'code': code, 'input': value}),
                               text=True, capture_output=True, timeout=10)
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize('mcp', [False, True], ids=['P2-missing-count', 'P3-label-and-missing-line'])
def test_mandatory_lines_use_actual_facts(mcp):
    value = fixture(mcp)
    code, result = run_guard(value, mcp)
    assert code == 0
    out = result[0]['json']
    assert out['status'] == 'PASS'
    assert out['raw_model_output'] == value['output']
    assert out['model_response'] == json.loads(value['output'])
    assert set(out['answer'].splitlines()) == {
        'Sale rows: 19', 'Net recorded sales: GBP -12.34', 'Gross sales: GBP 555.66',
        'Cancellation rows: 17', 'Cancellation magnitude: GBP 568.00',
        'Quality findings: 3', 'Missing customer sale rows: 2'}
    assert len(out['evidenced_facts']) == 7
    changed = deepcopy(value)
    body = json.loads(changed['intermediateSteps'][0]['observation'])
    actual = body[0]['structuredContent'] if mcp else body[0]
    actual['kpis']['cancellation_rows'] = 9
    changed['intermediateSteps'][0]['observation'] = json.dumps(body)
    code, result = run_guard(changed, mcp)
    assert code == 0 and 'Cancellation rows: 9' in result[0]['json']['answer']


@pytest.mark.parametrize('mcp', [False, True])
@pytest.mark.parametrize('tool_index', [0, 1], ids=['sales-only', 'quality-only'])
def test_existing_single_tool_paths_remain_supported(mcp, tool_index):
    value = fixture(mcp)
    value['intermediateSteps'] = [value['intermediateSteps'][tool_index]]
    name = json.loads(value['output'])['source_tools'][tool_index]
    value['output'] = json.dumps({'source_tools': [name]})
    code, result = run_guard(value, mcp)
    assert code == 0
    assert result[0]['json']['tools_used'] == [name]
    assert len(result[0]['json']['evidenced_facts']) == (5 if tool_index == 0 else 2)


@pytest.mark.parametrize('mcp', [False, True])
@pytest.mark.parametrize('defect', ['old-prose', 'missing-tool', 'extra-model-fact',
                                   'duplicate-call', 'write-response', 'missing-count',
                                   'bad-money', 'different-provenance'])
def test_invalid_model_or_tool_evidence_fails_closed(mcp, defect):
    value = fixture(mcp)
    if defect == 'old-prose':
        value['output'] = 'Cancellation magnitude gbp: GBP 568.00\nQuality findings: 3'
    elif defect == 'missing-tool':
        value['output'] = json.dumps({'source_tools': [json.loads(value['output'])['source_tools'][0]]})
    elif defect == 'extra-model-fact':
        value['output'] = json.dumps(dict(json.loads(value['output']), cancellation_rows=0))
    elif defect == 'duplicate-call':
        value['intermediateSteps'][1] = deepcopy(value['intermediateSteps'][0])
    else:
        body = json.loads(value['intermediateSteps'][0]['observation'])
        actual = body[0]['structuredContent'] if mcp else body[0]
        if defect == 'write-response': actual['access'] = 'write'
        elif defect == 'missing-count': del actual['kpis']['cancellation_rows']
        elif defect == 'bad-money': actual['kpis']['sales_value_gbp'] = 555.66
        else: actual['period'] = {'source_file_sha256': 'another-source'}
        value['intermediateSteps'][0]['observation'] = json.dumps(body)
    code, result = run_guard(value, mcp)
    assert code != 0 and result.get('error')


@pytest.mark.parametrize('defect', ['wrong-label', 'missing-count', 'false-zero', 'missing-customer-line'])
def test_retained_mcp_numeric_guard_still_rejects_bad_lines(defect):
    value = fixture(True)
    _, result = run_guard(value, True)
    answer = result[0]['json']['answer']
    if defect == 'wrong-label': answer = answer.replace('Cancellation magnitude:', 'Cancellation magnitude gbp:')
    elif defect == 'false-zero': answer = answer.replace('Cancellation rows: 17', 'Cancellation rows: 0')
    else:
        label = 'Cancellation rows:' if defect == 'missing-count' else 'Missing customer sale rows:'
        answer = '\n'.join(line for line in answer.splitlines() if not line.startswith(label))
    value['output'] = answer
    code, result = run_guard(value, True, legacy_only=True)
    assert code != 0 and result.get('error')
