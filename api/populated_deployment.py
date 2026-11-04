"""Non-admitting populated store preflight, independent of isolated app guards.

No credentials, connections, SQL executor, listener or business methods belong
here. Observations come from a trusted clone-only administrative READ ONLY probe.
A successful check is diagnostic evidence, NEVER an application/writer permit.
"""
from copy import deepcopy
from hashlib import sha256
import json
import re
from uuid import UUID


SCOPES = {
    'raa_wp4_portal_read_v2': (
        'api_portal_identity_v1(text)', 'api_owner_portal_request_v3(text,uuid)',
        'api_owner_portal_receipt_v2(text,uuid)', 'api_owner_portal_export_v2(text,uuid)',
        'api_owner_portal_review_v3(text,uuid,uuid)', 'api_owner_portal_requests_v3(text)',
        'api_owner_portal_transition_v1(text,uuid)', 'api_owner_retired_legacy_request_v1(text,uuid,uuid)'),
    'raa_wp4_portal_review_v2': ('api_decide_portal_request_v2(text,text,uuid,text,text,text)',
        'api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text)'),
    'raa_wp4_portal_issue_v3': ('api_issue_portal_request_v3(uuid,text,text,uuid)',),
    'raa_wp4_portal_transition_v1': ('api_transition_legacy_portal_v1(uuid,uuid,text,text,text)',
        'api_portal_transition_state_v1(uuid,text)'),
    'raa_wp4_portal_auth_v2': ('api_portal_auth_identity_v2(text)',
        'api_portal_auth_login_v2(text,text,text,text)', 'api_portal_auth_logout_v2(text,text)'),
    'raa_wp4_portal_attempt_v1': ('api_portal_attempt_state_v1(uuid,text)',
        'api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text)',
        'api_accept_portal_attempt_v1(uuid,text,uuid,text)',
        'api_report_portal_attempt_v1(uuid,text,uuid,text,text)', 'api_reconcile_portal_attempt_v1(uuid,text)'),
    # Internal dependencies are inventoried, not admitted as runtime stores.
    'raa_wp4_portal_recovery_v1': ('api_operator_reconcile_portal_v1(uuid,text,text)',),
    'raa_wp4_portal_publish_v2': ('api_accept_portal_publication_v2(uuid,text)',
        'api_portal_publication_state_v2(uuid)'),
    'raa_wp4_portal_worker_v2': ('api_worker_portal_state_v2(uuid,text)',
        'api_worker_accept_portal_v2(uuid,text,uuid,text,text)'),
}
BLOCKERS = ('continuous-maintenance-fence', 'existing-session-fence',
            'runtime-epoch', 'restored-xid-quarantine', 'fresh-login-custody',
            'future-function-default-privileges')


class DeploymentPreflightDenied(ValueError):
    """Finite, secret-free diagnostic; never include supplied values."""


def require(condition):
    if not condition:
        raise DeploymentPreflightDenied('Populated preflight denied')


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def canonical_id(value):
    require(isinstance(value, str) and str(UUID(value)) == value)


def hash_value(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None)


class PopulatedDeploymentStorePreflight:
    """Closed rehearsal configuration; deliberately cannot start or dispatch."""

    def __init__(self, config):
        try:
            require(type(config) is dict and set(config) == {
                'mode', 'database', 'system', 'checkpoint_id', 'catalog_sha256', 'receipts'})
            require(config['mode'] == 'clone-only-preflight-v1')
            require(isinstance(config['database'], str) and re.fullmatch(
                r'raa_wp4_populated_rehearsal_[a-f0-9]{12}', config['database']) is not None)
            require(isinstance(config['system'], str) and re.fullmatch(r'[0-9]{10,20}', config['system']) is not None)
            canonical_id(config['checkpoint_id']); hash_value(config['catalog_sha256'])
            receipts = config['receipts']
            require(type(receipts) is list and len(receipts) == 3)
            for index, receipt in enumerate(receipts):
                fields = {'bundle_id', 'deployment_id', 'checkpoint_id', 'source_digest',
                    'bundle_digest', 'baseline_digest', 'predecessor_id', 'base_version',
                    'target_database', 'target_system', 'admitted'}
                if index:
                    fields.add('predecessor_digest')
                require(type(receipt) is dict and set(receipt) == fields)
                require(receipt['bundle_id'] == 'wp4-rehearsal-00' + str(index + 1))
                canonical_id(receipt['deployment_id'])
                require(receipt['checkpoint_id'] == config['checkpoint_id']
                    and receipt['target_database'] == config['database']
                    and receipt['target_system'] == config['system']
                    and type(receipt['base_version']) is int and receipt['base_version'] == 20
                    and receipt['admitted'] is False)
                for field in ('source_digest', 'bundle_digest', 'baseline_digest'):
                    hash_value(receipt[field])
                if index:
                    prior = receipts[index - 1]
                    require(receipt['predecessor_id'] == prior['deployment_id']
                        and receipt['predecessor_digest'] == prior['bundle_digest']
                        and receipt['source_digest'] == prior['source_digest']
                        and receipt['baseline_digest'] == prior['baseline_digest'])
                else:
                    require(receipt['predecessor_id'] is None)
            require(len({r['deployment_id'] for r in receipts}) == 3)
            self._config = deepcopy(config)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise DeploymentPreflightDenied('Populated preflight denied') from None

    def check(self, observation):
        """Check one bounded snapshot; no freshness/continuous authority claimed."""
        try:
            config = self._config
            require(type(observation) is dict and set(observation) == {
                'database', 'system', 'read_only', 'versions', 'catalog_sha256',
                'receipts', 'roles', 'public_functions', 'unsafe_defaults'})
            require(observation['database'] == config['database']
                and observation['system'] == config['system']
                and observation['read_only'] is True
                and observation['versions'] == list(range(1, 21))
                and all(type(v) is int for v in observation['versions'])
                and observation['catalog_sha256'] == config['catalog_sha256']
                and digest(observation['receipts']) == digest(config['receipts']))
            for name in ('public_functions', 'unsafe_defaults'):
                require(type(observation[name]) is int and observation[name] == 0)
            roles = observation['roles']
            require(type(roles) is dict and set(roles) == set(SCOPES))
            for name, signatures in SCOPES.items():
                role = roles[name]
                require(type(role) is dict and set(role) == {'flags', 'functions',
                    'memberships', 'database_power', 'schema_power', 'object_rights', 'ownership'})
                require(type(role['flags']) is list and len(role['flags']) == 6
                    and all(flag is False for flag in role['flags']))
                require(type(role['functions']) is list
                    and all(type(fn) is str for fn in role['functions'])
                    and sorted(role['functions']) == sorted(signatures))
                for field in ('memberships', 'database_power', 'schema_power', 'object_rights', 'ownership'):
                    require(type(role[field]) is int and role[field] == 0)
            return dict(configuration_verified=True, application_writers_admitted=False,
                        runtime_start_allowed=False, blockers=list(BLOCKERS))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise DeploymentPreflightDenied('Populated preflight denied') from None

    def start(self):
        raise DeploymentPreflightDenied('Runtime admission is not implemented')

    def execute(self, *args, **kwargs):
        raise DeploymentPreflightDenied('Runtime admission is not implemented')
