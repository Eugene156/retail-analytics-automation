"""Bounded publication/static checks; never print matched secret contents.

Checks the index plus non-ignored untracked candidates before a first commit,
and tracked files on CI. Known local secret comparison is an additional local
check, not a complete credential/privacy detector. No Docker or network calls.
"""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {'.local', '.codex', '.agents', 'credentials', 'secrets',
                   'sessions', 'execution-history', 'execution_history',
                   'executions', 'dumps', 'backups', 'models', 'volumes'}
FORBIDDEN_SUFFIXES = {'.dump', '.backup', '.sqlite', '.sqlite3', '.db', '.pem', '.key'}
SECRET_PATTERN = re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|'
                            rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')


def candidates():
    result = subprocess.run(['git', 'ls-files', '--cached', '--others',
                             '--exclude-standard', '-z'], cwd=ROOT,
                            capture_output=True, check=True)
    return sorted(set(p for p in result.stdout.decode().split('\0') if p))


def local_secrets():
    """Read only bounded credential files; discard templates and metadata."""
    values = set()
    for path in (ROOT / '.local').rglob('*'):
        if not path.is_file() or path.stat().st_size > 10000:
            continue
        if not any(x in path.name.lower() for x in ('password', 'token', 'key', 'dsn', '.env')):
            continue
        try:
            text = path.read_text().strip()
        except (UnicodeError, OSError):
            continue
        if re.fullmatch(r'[a-fA-F0-9]{32,128}', text):
            values.add(text.encode())
        if path.name == '.env':
            for line in text.splitlines():
                if '=' in line:
                    value = line.split('=', 1)[1].strip()
                    if re.fullmatch(r'[a-fA-F0-9]{32,128}', value):
                        values.add(value.encode())
        for value in re.findall(r'postgres(?:ql)?://[^:\s]+:([^@\s]+)@', text):
            if len(value) >= 20 and not any(c in value for c in '${}'):
                values.add(value.encode())
    return values


def inspect(path, secrets):
    relative = Path(path)
    if (set(relative.parts) & FORBIDDEN_PARTS or relative.suffix.lower() in FORBIDDEN_SUFFIXES
            or (relative.name.startswith('.env') and relative.name != '.env.example')
            or path.startswith(('data/raw/', 'data/processed/', 'evidence/private/', 'reports/private/'))
            or re.search(r'credentials.*\.json$|executions.*\.json$|execution-data.*\.json$', path)
            or (path.startswith('evidence/') and relative.suffix.lower() in {'.png', '.jpg', '.jpeg'})):
        return 'private/unreviewed path'
    data = (ROOT / path).read_bytes()
    if SECRET_PATTERN.search(data) or any(value in data for value in secrets):
        return 'secret detected'
    if relative.suffix == '.py':
        ast.parse(data, filename=path)
    if relative.suffix == '.json':
        value = json.loads(data)
        if path.startswith(('evidence/', 'workflows/')) and re.search(
                rb'"(?:contextData|runData|executionData)"\s*:', data):
            return 'raw execution data'
        if path.startswith('workflows/'):
            if value.get('pinData'):
                return 'pinned workflow data'
            for node in value.get('nodes', []):
                # Credential ID/type references are expected; plaintext values are not.
                if re.search(rb'"(?:Authorization|X-API-Key)"\s*:\s*"(?:Bearer )?[A-Za-z0-9_-]{24,}',
                             json.dumps(node.get('parameters', {})).encode(), re.I):
                    return 'literal authentication header'
    return None


def check_ci():
    import yaml
    # BaseLoader preserves the Actions key "on" instead of interpreting YAML1.1 boolean.
    workflow = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    assert set(workflow['on']) == {'push', 'pull_request', 'workflow_dispatch'}
    assert workflow['permissions'] == {'contents': 'read'}
    job = workflow['jobs']['checks']
    assert job['timeout-minutes'] == '5' and job['runs-on'] == 'ubuntu-latest'
    assert not any(key in job for key in ('services', 'container', 'secrets'))
    steps = job['steps']
    assert steps[0]['with']['persist-credentials'] == 'false'
    assert steps[1]['with']['python-version'] == '3.12'
    assert [s['run'] for s in steps if 'run' in s] == [
        'python -m pip install -r config/ci-requirements.txt',
        'python scripts/check_publication.py',
        'python -m pytest -q tests/test_wp4_recovery_design.py tests/test_wp3_n8n_local.py tests/test_publication_security.py tests/test_ai_evaluation.py tests/test_api_docs.py tests/test_observability.py']


def main():
    paths, secrets = candidates(), local_secrets()
    problems = []
    for path in paths:
        try:
            problem = inspect(path, secrets)
        except (ValueError, SyntaxError, OSError):
            problem = 'invalid/unreadable source'
        if problem:
            problems.append((path, problem))
    check_ci()
    for path, problem in problems:
        print(f'FAIL: {path}: {problem}')
    print(f'Candidates={len(paths)}; local_secret_values_compared={len(secrets)}; '
          f'publication/static/YAML={"FAIL" if problems else "PASS"}')
    return bool(problems)


if __name__ == '__main__':
    sys.exit(main())
