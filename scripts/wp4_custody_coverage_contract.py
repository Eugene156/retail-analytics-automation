"""Offline source/plan audit only. No connection, SQL execution or writer permit."""
import ast
from copy import deepcopy
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'wp4-custody-coverage-plan-v1'
PORTAL = {
 'raa_wp4_portal_read_v2': ('api_portal_identity_v1(text)', 'api_owner_portal_request_v3(text,uuid)',
  'api_owner_portal_receipt_v2(text,uuid)', 'api_owner_portal_export_v2(text,uuid)',
  'api_owner_portal_review_v3(text,uuid,uuid)', 'api_owner_portal_requests_v3(text)',
  'api_owner_portal_transition_v1(text,uuid)', 'api_owner_retired_legacy_request_v1(text,uuid,uuid)'),
 'raa_wp4_portal_review_v2': ('api_decide_portal_request_v2(text,text,uuid,text,text,text)',
  'api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text)'),
 'raa_wp4_portal_issue_v3': ('api_issue_portal_request_v3(uuid,text,text,uuid)',),
 'raa_wp4_portal_transition_v1': ('api_transition_legacy_portal_v1(uuid,uuid,text,text,text)', 'api_portal_transition_state_v1(uuid,text)'),
 'raa_wp4_portal_auth_v2': ('api_portal_auth_identity_v2(text)', 'api_portal_auth_login_v2(text,text,text,text)', 'api_portal_auth_logout_v2(text,text)'),
 'raa_wp4_portal_attempt_v1': ('api_portal_attempt_state_v1(uuid,text)',
  'api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text)', 'api_accept_portal_attempt_v1(uuid,text,uuid,text)',
  'api_report_portal_attempt_v1(uuid,text,uuid,text,text)', 'api_reconcile_portal_attempt_v1(uuid,text)'),
 'raa_wp4_portal_recovery_v1': ('api_operator_reconcile_portal_v1(uuid,text,text)',),
 'raa_wp4_portal_publish_v2': ('api_accept_portal_publication_v2(uuid,text)', 'api_portal_publication_state_v2(uuid)'),
 'raa_wp4_portal_worker_v2': ('api_worker_portal_state_v2(uuid,text)', 'api_worker_accept_portal_v2(uuid,text,uuid,text,text)'),
}
LEGACY = {
 'raa_wp2_api': ('api_comparison_report_v1(text,timestamp,timestamp,timestamp)',),
 'raa_wp2_case_api': ('api_reserve_report_v1(text,text,timestamp,timestamp,timestamp)', 'api_finish_report_v1(uuid)',
  'api_get_case_v1(uuid)', 'api_get_revision_v1(uuid,integer)', 'api_get_approval_proposal_v1(uuid)',
  'api_get_approval_request_v2(uuid,uuid)', 'api_current_approval_request_v2(uuid)',
  'api_issue_approval_request_v2(uuid,integer,text,text,uuid)'),
 'raa_wp4_reviewer_api': ('api_owner_identity_v1(text)', 'api_owner_case_v1(text,uuid)',
  'api_owner_revision_v1(text,uuid,integer)', 'api_owner_proposal_v1(text,uuid)',
  'api_owner_approval_request_v2(text,uuid,uuid)', 'api_owner_current_request_v2(text,uuid)'),
 'raa_wp4_portal_api': ('api_portal_identity_v1(text)', 'api_portal_login_v1(text,text,text,text)',
  'api_portal_logout_v1(text,text)', 'api_portal_requests_v1(text)', 'api_portal_request_v1(text,uuid,uuid)',
  'api_portal_case_v1(text,uuid)', 'api_portal_revision_v1(text,uuid,integer)',
  'api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)', 'api_decision_snapshot_v1(text,uuid,uuid)'),
 'raa_wp4_decision_api': ('api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)',
  'api_decision_snapshot_v1(text,uuid,uuid)'),
}
MUTATORS = frozenset(('api_reserve_report_v1','api_finish_report_v1','api_issue_approval_request_v2',
 'api_portal_login_v1','api_portal_logout_v1','api_decide_request_v1',
 'api_decide_portal_request_v2','api_owner_decide_portal_request_v3','api_issue_portal_request_v3',
 'api_transition_legacy_portal_v1','api_portal_auth_login_v2','api_portal_auth_logout_v2',
 'api_reserve_portal_attempt_v1','api_accept_portal_attempt_v1','api_report_portal_attempt_v1',
 'api_reconcile_portal_attempt_v1','api_operator_reconcile_portal_v1',
 'api_accept_portal_publication_v2','api_worker_accept_portal_v2'))
MIGRATIONS = ('012_comparison_api_boundary.sql','013_report_requests.sql','015_immutable_approval_proposals.sql',
 '016_owner_read_auth.sql','017_explicit_approval_requests.sql','018_owner_portal_sessions.sql',
 '019_decision_outbox_foundation.sql','020_portal_decision_projection.sql')
APPS = ('__init__.py','local_publication.py','main.py','populated_deployment.py','portal.py','portal_attempts.py',
 'portal_auth_v2.py','portal_publication.py','portal_review_v3.py','portal_transition_v1.py','portal_uat.py',
 'portal_worker_v2.py','preview.py','publication_dispatch.py','reviewer.py')
QUARANTINED = frozenset(('api_authorize_publication_v1','api_claim_publication_v1',
                        'api_observe_publication_v1','api_publication_state_v1'))
SERVER_FIELDS = ('system_identifier','postmaster_start','database_oid','session_user_oid',
                 'backend_pid','backend_start','custody_release_id')
CASES = {
 'same-uuid-different-backend': dict(owner_matches=False,mutation=False),
 'same-pid-different-start': dict(owner_matches=False,mutation=False),
 'same-role-fresh-connection': dict(owner_matches=False,mutation=False),
 'caller-epoch-or-guc': dict(server_identity_required=True,caller_authority=False),
 'definer-current-user': dict(session_identity_required=True,definer_owner_is_caller=False),
 'owner-backend-gone': dict(custody_retained=True,takeover=False,runtime=False),
 'copied-custody-or-server-restart': dict(old_custody_accepted=False,runtime=False),
 'raw004-close-bypass': dict(controller_execute=False,new_owned_path_required=True),
 'unknown-or-prepared': dict(quiescent=False,automatic_resolution=False,runtime=False),
 'read-route-and-direct-call': dict(guard_first=True,closed_business_entry=False),
 'savepoint-or-exception': dict(cached_authorization=False,every_entry_rechecks=True),
 'read-only-or-isolation-mismatch': dict(transaction_mode_denied=True,unguarded_fallback=False),
 'ddl-or-effective-acl-drift': dict(runtime=False,allowlist_auto_extended=False),
 'original-deadline-and-slots': dict(deadline_renewed=False,slot_reset=False,history_preserved=True),
}


class CoverageDenied(ValueError):
    """Finite diagnostic, never include source/identity/credential values."""


def require(value):
    if not value:
        raise CoverageDenied('Custody coverage contract denied')


def exact(value, expected):
    require(type(value) is type(expected))
    if type(expected) is dict:
        require(set(value) == set(expected))
        for key in expected: exact(value[key],expected[key])
    elif type(expected) in (tuple,list):
        require(len(value) == len(expected))
        for a,b in zip(value,expected): exact(a,b)
    else:
        require(value == expected)


def routes():
    result = {}
    for role, signatures in {**PORTAL,**LEGACY}.items():
        for signature in signatures:
            row = result.setdefault(signature,dict(roles=[],effect=('mutates' if signature.split('(')[0] in MUTATORS else 'read-or-lock'),
                guard='same-transaction-before-business',closed='deny',implemented=False))
            row['roles'].append(role)
    for row in result.values(): row['roles'].sort()
    return dict(sorted(result.items()))


def planned_contract():
    return dict(version=VERSION,scope='fresh-populated-clone-only',evidence_status='planned',
        native_scenarios_executed=0,runtime_start_allowed=False,application_writers_admitted=False,
        routes=routes(),custody=dict(server_fields=list(SERVER_FIELDS),persistent_connection=True,
            caller_identity_authoritative=False,authenticated_runtime_identity_verified=False,
            takeover=False,old004_close_execute=False),
        guard=dict(latch_lock='FOR SHARE',close_lock='FOR UPDATE',isolation='read committed',
            transaction_mode='read write',every_entry=True,cached_permit=False,
            savepoint_escape=False,preserve_function_oid=True,rename_original=False,
            volatility='volatile',parallel='unsafe',called_on_null=True,
            owner_helper_privilege='exact-private-helper-only'),
        excluded_paths=['raw-ingestion-and-maintenance','privileged-bootstrap','n8n-ui-cli-runner-scheduler',
                        'NTFS-dispatch','restored-writer-admission'],
        scenarios=deepcopy(CASES))


def check_plan(plan):
    exact(plan,planned_contract())
    return dict(roles=len({role for row in plan['routes'].values() for role in row['roles']}),
                bindings=sum(len(row['roles']) for row in plan['routes'].values()),
                functions=len(plan['routes']),mutators=sum(row['effect']=='mutates' for row in plan['routes'].values()),
                planned_scenarios=len(CASES),native_execution_proved=False,runtime_start_allowed=False,
                application_writers_admitted=False)


def acl_projection(sources):
    """Only the fixed literal EXECUTE grant/revoke subset, NOT a SQL parser."""
    active = {}
    for source in sources:
        for action,items,direction,grantee in re.findall(
            r'(GRANT|REVOKE) EXECUTE ON FUNCTION\s+([^;]+?)\s+(TO|FROM)\s+([a-z0-9_]+)\s*;',source):
            require((action,direction) in (('GRANT','TO'),('REVOKE','FROM')))
            signatures = re.findall(r'retail\.([a-z0-9_]+\([a-z0-9_,\s]*\))',items)
            rest = re.sub(r'retail\.[a-z0-9_]+\([a-z0-9_,\s]*\)','',items)
            require(signatures and not rest.replace(',','').strip())
            group = active.setdefault(grantee,set())
            for signature in signatures:
                value = re.sub(r'\s+','',signature)
                if action == 'GRANT': group.add(value)
                else:
                    require(value in group);group.remove(value)
    return {role:tuple(sorted(values)) for role,values in active.items()}


def source_files():
    require({p.name for p in (ROOT/'api').glob('*.py')} == set(APPS))
    paths = ['api/'+name for name in APPS]+['db/migrations/'+name for name in MIGRATIONS]+[
        'db/deployment/002_portal_schema_rehearsal.sql']
    return {path:(ROOT/path).read_text(encoding='utf-8') for path in paths}


def audit_sources(files=None):
    files = source_files() if files is None else files
    required = {'api/'+name for name in APPS}|{'db/migrations/'+name for name in MIGRATIONS}|{
        'db/deployment/002_portal_schema_rehearsal.sql'}
    require(type(files) is dict and set(files) == required and all(type(s) is str for s in files.values()))
    nodes = [n for n in ast.parse(files['api/populated_deployment.py']).body if isinstance(n,ast.Assign)
             and any(isinstance(t,ast.Name) and t.id == 'SCOPES' for t in n.targets)]
    require(len(nodes) == 1); exact(ast.literal_eval(nodes[0].value),PORTAL)
    normalize = lambda mapping:{k:tuple(sorted(v)) for k,v in mapping.items()}
    exact(acl_projection([files['db/migrations/'+name] for name in MIGRATIONS]),normalize(LEGACY))
    exact(acl_projection([files['db/deployment/002_portal_schema_rehearsal.sql']]),normalize(PORTAL))
    names = {signature.split('(')[0] for signature in routes()}
    calls = set()
    for name in APPS:
        found = set(re.findall(r'retail\.(api_[a-z0-9_]+)\(',files['api/'+name]))
        require(found <= (QUARANTINED if name=='publication_dispatch.py' else names))
        calls |= found
    require(QUARANTINED <= calls)
    return dict(source_projection_verified=True,functions=len(names),
                quarantined_dispatch_names=len(QUARANTINED),effective_native_acl_verified=False,
                guard_implementation_verified=False,runtime_start_allowed=False)


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 1:
        print('FAIL|custody-coverage|no-target-or-live-option');raise SystemExit(1)
    try:
        result=check_plan(planned_contract());audit_sources()
    except (CoverageDenied,ValueError,SyntaxError,TypeError,OSError):
        print('FAIL|custody-coverage|source-or-plan-denied');raise SystemExit(1) from None
    print('PASS|offline-custody-coverage|'+str(result['roles'])+'-roles|'+str(result['functions'])+
          '-functions|'+str(result['bindings'])+'-bindings|native-not-run')
    print('BLOCKED|runtime-admission|custody-business-hooks-not-implemented')
    raise SystemExit(2)
