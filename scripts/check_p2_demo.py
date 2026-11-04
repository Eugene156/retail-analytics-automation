"""Read only P2 executions; check secrets privately and emit bounded evidence."""
import argparse
import json
import subprocess

import p1_demo as p1
from p2_demo import PARENT, CORE, TOKEN


def unflatten(text):
    values = json.loads(text)
    if not values:
        return {}
    memo = {}
    def item(index):
        if index in memo:
            return memo[index]
        value = values[index]
        if isinstance(value, dict):
            result = {}; memo[index] = result
            result.update({k: ref(v) for k, v in value.items()})
        elif isinstance(value, list):
            result = []; memo[index] = result
            result.extend(ref(v) for v in value)
        else:
            result = value; memo[index] = result
        return result
    def ref(value):
        return item(int(value)) if isinstance(value, str) and value.isdigit() else value
    return item(0)


def main(save=False):
    p1.guard()
    protected = [TOKEN.read_text().strip(), (p1.PRIVATE / 'api/token').read_text().strip()]
    rows = p1.sql("BEGIN READ ONLY; SELECT json_build_object('id',e.id,'workflow',e.\"workflowId\",'status',e.status,'data',d.data) FROM execution_entity e LEFT JOIN execution_data d ON d.\"executionId\"=e.id WHERE e.\"workflowId\" IN ('" + PARENT + "','" + CORE + "') ORDER BY e.id; COMMIT;", 'n8n')
    assert not any(secret in rows for secret in protected), 'P2 history secret leak'
    evidence = []
    for line in rows.splitlines():
        row = json.loads(line)
        summary = {k: row[k] for k in ('id', 'workflow', 'status')}
        if row['data']:
            data = unflatten(row['data'])
            results = data.get('resultData', {})
            if results.get('error'):
                summary['error'] = results['error'].get('message', 'Execution error')[:400]
            runs = results.get('runData', {})
            if 'Validate question' in runs:
                summary['question'] = runs['Validate question'][-1]['data']['main'][0][0]['json']['question']
            if 'Validate tool evidence' in runs and runs['Validate tool evidence'][-1].get('data'):
                output = runs['Validate tool evidence'][-1]['data']['main'][0][0]['json']
                summary.update(status=output['status'], tools_used=output['tools_used'], answer=output['answer'])
            elif 'Safe failure' in runs:
                summary['agent_status'] = 'BLOCKED'
                agent = runs.get('AI Agent', [{}])[-1]
                summary['agent_error'] = str(agent.get('error', {}).get('message', 'See core execution'))[:400]
                branches = agent.get('data', {}).get('main', [])
                for branch in branches:
                    for entry in branch or []:
                        if 'error' in entry.get('json', {}):
                            summary['agent_error'] = str(entry['json']['error'])[:800]
        evidence.append(summary)
    for container in ['raa-p1-demo-api-1', 'raa-p1-demo-n8n-1', 'raa-p2-demo-ollama-1']:
        logs = subprocess.run(['docker', '--context', 'desktop-linux', 'logs', '--since', '30m', container], capture_output=True, check=True)
        assert not any(secret.encode() in logs.stdout + logs.stderr for secret in protected), 'P2 log secret leak'
    assert p1.sql('SELECT count(*) FROM execution_entity WHERE id IN (6,8);', 'n8n') == '2'
    for path in [p1.ROOT / 'workflows/p2_read_agent_demo.json', p1.ROOT / 'workflows/p2_read_agent_core.json']:
        assert not any(secret in path.read_text() for secret in protected)
    tracked = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, check=True).stdout.split(b'\0')
    for filename in filter(None, tracked):
        path = p1.ROOT / filename.decode()
        if path.is_file():
            assert not any(secret.encode() in path.read_bytes() for secret in protected)
        staged = subprocess.run(['git', 'show', ':' + filename.decode()], capture_output=True)
        assert not any(secret.encode() in staged.stdout for secret in protected)
    assert subprocess.run(['git', 'check-ignore', str(TOKEN)], capture_output=True).returncode == 0
    credentials = p1.sql("SELECT data FROM credentials_entity WHERE id IN ('p2-read-api','p2-ollama');", 'n8n').splitlines()
    assert len(credentials) == 2 and all(value and not value.startswith('{') for value in credentials)
    assert not any(secret in value for secret in protected for value in credentials)
    receipt = {'history_and_logs_secret_scan': 'PASS', 'Git_secret_scan': 'PASS',
               'encrypted_credentials_at_rest': True, 'old_executions_retained': True, 'executions': evidence}
    if save:
        cores = [e for e in evidence if e['workflow'] == CORE and e['status'] == 'PASS' and e['id'] >= 24]
        expected = {('Get_Sales_KPIs',), ('Get_Data_Quality',), ('Get_Data_Quality', 'Get_Sales_KPIs')}
        assert expected.issubset({tuple(e['tools_used']) for e in cores}), 'Three actual scenarios required'
        receipt['scope'] = 'P2 actual n8n manual executions, native AI Agent and local Ollama'
        receipt['workflow_url'] = 'http://127.0.0.1:15690/workflow/' + PARENT
        (p1.ROOT / 'evidence/p2_ai_agent.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', action='store_true')
    main(parser.parse_args().save)
