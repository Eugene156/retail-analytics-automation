"""P1-only fresh demo preparation, initialization and real draft verification.

No historical dump, credential registry, old service or native008 helper is used.
initialize/check mutate Docker resources: run only after explicit owner approval.
"""
import argparse
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.local/p1-demo'
COMPOSE = ['compose', '--env-file', str(PRIVATE / '.env'), '-f', str(ROOT / 'demo/compose.yaml')]
PG = 'raa-p1-demo-postgres-1'
WORKFLOW_ID = 'raa-p1-demo-draft-v1'
SOURCE = ROOT / 'workflows/wp3_manual_draft.json'
WORKFLOW = ROOT / 'workflows/p1_manual_report.json'


def require(value, label):
    if not value:
        raise RuntimeError(label)


def workflow():
    value = json.loads(SOURCE.read_text(encoding='utf-8'))
    require(value['active'] is False and not value.get('pinData'), 'inactive-source-required')
    require(all('credentials' not in node for node in value['nodes']), 'sanitized-source-required')
    value['id'] = WORKFLOW_ID
    value['name'] = 'P1 Isolated Historical Report - Unapproved'
    for node in value['nodes']:
        if 'url' in node['parameters']:
            node['parameters']['url'] = node['parameters']['url'].replace('raa-wp2-api:8000', 'api:8000')
    return value


def prepare():
    require(not PRIVATE.exists(), 'existing-demo-config-preserved')
    from wp2_import_workbook import WORKBOOK, EXPECTED_SIZE, EXPECTED_SHA256, sha256_file
    require(WORKBOOK.stat().st_size == EXPECTED_SIZE and sha256_file(WORKBOOK) == EXPECTED_SHA256,
            'pinned-public-workbook-required')
    PRIVATE.mkdir(parents=True)
    (PRIVATE / 'api').mkdir()
    values = {name: secrets.token_hex(32) for name in
              ('P1_POSTGRES_PASSWORD', 'P1_N8N_ENCRYPTION_KEY', 'P1_RUNNER_TOKEN')}
    (PRIVATE / '.env').write_text(''.join(k+'='+v+'\n' for k, v in values.items()), encoding='utf-8')
    for name, value in {'token': secrets.token_hex(32),
                        'dsn': 'postgresql://raa_wp2_api:'+secrets.token_hex(32)+'@postgres:5432/raa_wp2_validation',
                        'case-dsn': 'postgresql://raa_wp2_case_api:'+secrets.token_hex(32)+'@postgres:5432/raa_wp2_validation'}.items():
        (PRIVATE / 'api' / name).write_text(value+'\n', encoding='utf-8')
    WORKFLOW.write_text(json.dumps(workflow(), indent=2)+'\n', encoding='utf-8')
    print('PREPARED|fresh-ignored-secrets|pinned-public-workbook|sanitized-workflow|no-Docker-mutation')


def docker(args, stdin=None, timeout=300):
    result = subprocess.run(['docker', '--context', 'desktop-linux', *args], input=stdin,
                            text=True, encoding='utf-8', capture_output=True, timeout=timeout)
    # Never echo Docker/SQL stderr, credentials or connection strings.
    require(result.returncode == 0, 'demo-Docker-operation-failed')
    return result.stdout


def guard():
    labels = json.loads(docker(['inspect', PG, '--format', '{{json .Config.Labels}}']))
    require(labels.get('com.docker.compose.project') == 'raa-p1-demo' and
            labels.get('com.docker.compose.service') == 'postgres', 'demo-postgres-ownership')
    mounts = json.loads(docker(['inspect', PG, '--format', '{{json .Mounts}}']))
    require(len(mounts) == 1 and mounts[0].get('Name') == 'raa-p1-demo_postgres_data', 'fresh-demo-volume-only')
    require(WORKFLOW.read_text(encoding='utf-8') == json.dumps(workflow(), indent=2)+'\n', 'exact-derived-workflow')


def sql(statement, database='raa_wp2_validation'):
    return docker(['exec', '-i', PG, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
                   '-U', 'g0_user', '-d', database, '-f', '-'], statement, timeout=1200).strip()


def initialize():
    guard()
    require(sql("SELECT count(*) FROM pg_database WHERE datname='raa_wp2_validation';", 'n8n') == '0',
            'fresh-business-database-required-no-reset')
    docker(['exec', PG, 'createdb', '-U', 'g0_user', 'raa_wp2_validation'])
    migrations = sorted((ROOT / 'db/migrations').glob('*.sql'))
    for version in range(1, 15):
        files = [path for path in migrations if path.name.startswith(f'{version:03d}_')]
        require(len(files) == 1, 'one-migration-per-version')
        sql('BEGIN;\n'+files[0].read_text(encoding='utf-8')+'\nCOMMIT;')
    # Reuse the existing complete physical-row importer; only its container target changes.
    import wp2_import_workbook as importer
    importer.CONTAINER = PG
    os.environ['DOCKER_CONTEXT'] = 'desktop-linux'
    importer.import_workbook('p1-demo-full-public-v1')
    sql("SELECT * FROM retail.classify_snapshot_v1('"+importer.EXPECTED_SHA256+"');")
    require(sql('SELECT count(*) FROM retail.source_rows;') == '1067371', 'complete-source-row-count')
    for name, role in (('dsn', 'raa_wp2_api'), ('case-dsn', 'raa_wp2_case_api')):
        from urllib.parse import urlparse
        dsn = urlparse((PRIVATE / 'api' / name).read_text(encoding='utf-8').strip())
        require(dsn.hostname == 'postgres' and dsn.username == role and dsn.path == '/raa_wp2_validation',
                'demo-scoped-dsn')
        require(len(dsn.password) == 64 and all(c in '0123456789abcdef' for c in dsn.password), 'demo-password-format')
        sql("ALTER ROLE "+role+" LOGIN PASSWORD '"+dsn.password+"';")
    (PRIVATE / 'initialized.json').write_text(json.dumps({'source_rows': 1067371, 'migrations': 14})+'\n')
    print('INITIALIZED|new-cluster-only|14-unchanged-migrations|1067371-public-source-rows|fresh-scoped-logins')


def check():
    guard()
    require((PRIVATE / 'initialized.json').is_file(), 'initialized-demo-required')
    # CLI broker must own n8n's alias. Do not stop any existing/background n8n.
    require(not docker(['ps', '--filter', 'label=com.docker.compose.project=raa-p1-demo',
                        '--filter', 'label=com.docker.compose.service=n8n', '--format', '{{.ID}}']).strip(),
            'demo-n8n-service-must-be-stopped-before-CLI')
    token = (PRIVATE / 'api/token').read_text(encoding='utf-8').strip()
    headers = {'Authorization': 'Bearer '+token}
    with urlopen(Request('http://127.0.0.1:18090/readyz', headers=headers), timeout=10) as response:
        require(response.status == 200, 'real-API-DB-readiness')
    credential = {'id': 'p1-demo-api-auth', 'name': 'P1 isolated report API', 'type': 'httpHeaderAuth',
                  'data': {'name': 'Authorization', 'value': 'Bearer '+token}}
    docker(COMPOSE+['run', '--pull', 'never', '--no-deps', '-T', 'n8n', 'import:credentials', '--input=/dev/stdin'],
           json.dumps([credential]))
    value = workflow()
    for node in value['nodes']:
        if node['type'] == 'n8n-nodes-base.httpRequest':
            node['credentials'] = {'httpHeaderAuth': {k: credential[k] for k in ('id', 'name')}}
    docker(COMPOSE+['run', '--pull', 'never', '--no-deps', '-T', 'n8n', 'import:workflow', '--input=/dev/stdin'], json.dumps(value))
    result = docker(COMPOSE+['run', '--pull', 'never', '--no-deps', '--use-aliases', '-T',
                            'n8n', 'execute', '--id='+WORKFLOW_ID, '--rawOutput'], timeout=650)
    # Pure JSON extraction helper only: no old configuration/secret registry calls.
    from wp3_n8n_local import extract_json
    execution = extract_json(result, lambda v: isinstance(v, dict) and isinstance(v.get('data'), dict)
                             and 'resultData' in v['data'])
    data = execution['data']['resultData']
    require('error' not in data and data.get('lastNodeExecuted') == 'Verified unapproved draft', 'real-n8n-success')
    summary = data['runData']['Verified unapproved draft'][0]['data']['main'][0][0]['json']
    from uuid import UUID
    case = str(UUID(summary['case_id']))
    require(summary['status'] == 'unapproved_draft_verified', 'verified-draft-status')
    with urlopen(Request('http://127.0.0.1:18090/api/v1/cases/'+case+'/revisions/1', headers=headers), timeout=10) as response:
        raw = response.read()
    require(sha256(raw).hexdigest() == summary['payload_sha256'], 'actual-HTTP-report-hash')
    report = json.loads(raw, parse_float=Decimal)
    kpis = report['current_period']['kpis']
    require(kpis['period_source_rows'] == 74 and kpis['sales_value_gbp'] == Decimal('1349.45')
            and kpis['cancellation_magnitude_gbp'] == Decimal('1270.03'), 'independent-historical-M02-golden')
    require(sql('SELECT count(*) FROM retail.source_rows;') == '1067371', 'source-rows-preserved')
    (PRIVATE / 'report.json').write_bytes(raw)
    (PRIVATE / 'verification.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print('VERIFIED|real-n8n-FastAPI-PostgreSQL|M02-74-rows|sales-1349.45|cancellations-1270.03|unapproved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'initialize', 'check'])
    args = parser.parse_args()
    try:
        globals()[args.operation]()
    except Exception:
        raise SystemExit('BLOCKED|P1-demo|details-suppressed|preserve-resources-no-reset') from None
