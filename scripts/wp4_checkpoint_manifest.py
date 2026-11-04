"""Strict structural contract for a future coordinated PRIVATE checkpoint.

No capture, Docker, SQL, file I/O, restore, writer fencing or admission occurs.
An accepted record is captured-unrestored metadata, never proof of its claims.
Artifact hashes/key/config metadata are private and must not be printed/exported.
"""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
from uuid import UUID

VERSION='wp4-coordinated-checkpoint-v1'
SOURCES={
    'main':dict(database='raa_wp2_validation',schema='retail',migration=20),
    'uat':dict(database='raa_wp4_dispatch_test_71394e7af9bb',schema='retail',migration=29),
    'n8n':dict(database='n8n',schema='public',migration=None),
}
ARTIFACTS={
    'main_retail':'main-retail.dump',
    'uat_retail':'uat-retail.dump',
    'n8n_public':'n8n-public.dump',
    'n8n_home':'n8n-home.tar',
    'n8n_key':'n8n-key',
    'runtime_configs':'runtime-configs.tar',
    'roles_acls':'roles-acls.json',
    'database_fingerprints':'database-fingerprints.json',
    'source_bundle':'source-bundle.tar',
    'source_workbook':'source-workbook.xlsx',
}
WRITERS=('raa-wp2-api','raa-g0-n8n-1','raa-g0-runner-1','raa-wp4-portal-uat-71394e7af9bb-owner')
TOP={'contract_version','checkpoint_id','status','interval','sources','quiescence','artifacts',
     'runtime_pins','restoration_admitted'}


class ManifestError(Exception):
    """Only a fixed safe category, never values or secret-bearing metadata."""


def require(condition):
    if not condition:raise ManifestError('Checkpoint metadata denied')


def exact(value,keys):
    require(isinstance(value,dict) and set(value)==set(keys))


def moment(value):
    require(isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z',value))
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(result.utcoffset()==timedelta(0))
    return result


def validate(record,expected_pins):
    """Validate completeness/shape only; do not trust an unverified receipt as a grant."""
    try:
        exact(record,TOP)
        require(record['contract_version']==VERSION and record['status']=='captured-unrestored'
                and record['restoration_admitted'] is False)
        identity=record['checkpoint_id']
        require(isinstance(identity,str) and str(UUID(identity))==identity)
        exact(record['sources'],SOURCES)
        for kind,expected in SOURCES.items():
            exact(record['sources'][kind],expected)
            require(all(type(record['sources'][kind][key]) is type(value)
                        and record['sources'][kind][key]==value for key,value in expected.items()))
        exact(record['runtime_pins'],('postgresql','n8n','runner','api'))
        exact(expected_pins,('postgresql','n8n','runner','api'))
        require(all(isinstance(value,str) and re.fullmatch(r'(?:[a-z0-9./:_-]+@)?sha256:[a-f0-9]{64}',value)
                    for value in expected_pins.values()))
        require(record['runtime_pins']==expected_pins)
        exact(record['interval'],('fenced_at','capture_started_at','capture_finished_at','fence_verified_at'))
        times=[moment(record['interval'][key]) for key in
               ('fenced_at','capture_started_at','capture_finished_at','fence_verified_at')]
        require(times==sorted(times) and times[1]<times[2])
        q=record['quiescence']
        exact(q,('method','stopped_writers','application_sessions_before','application_sessions_after',
                 'active_workflows','inflight_executions','worker_containers_absent','old_writers_fenced'))
        require(q['method']=='maintenance-fence-v1' and q['stopped_writers']==list(WRITERS)
                and q['worker_containers_absent'] is True and q['old_writers_fenced'] is True)
        for key in ('active_workflows','inflight_executions'):
            require(type(q[key]) is int and q[key]==0)
        for key in ('application_sessions_before','application_sessions_after'):
            exact(q[key],SOURCES)
            require(all(type(n) is int and n==0 for n in q[key].values()))
        exact(record['artifacts'],ARTIFACTS)
        for key,name in ARTIFACTS.items():
            row=record['artifacts'][key]
            exact(row,('path','bytes','sha256','capture_started_at','capture_finished_at'))
            require(row['path']==name and type(row['bytes']) is int and 0<row['bytes']<=2**40)
            require(isinstance(row['sha256'],str) and re.fullmatch(r'[a-f0-9]{64}',row['sha256']))
            start,end=moment(row['capture_started_at']),moment(row['capture_finished_at'])
            require(times[1]<=start<=end<=times[2])
        # Digest is for PRIVATE byte identity, not a signature or authorization.
        raw=json.dumps(record,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('utf-8')
        return sha256(raw).hexdigest()
    except ManifestError:raise
    except (ValueError,TypeError,KeyError,OverflowError,AttributeError,RecursionError):
        raise ManifestError('Checkpoint metadata denied') from None


def parse(raw,expected_pins):
    """Duplicate keys/NaN/huge input cannot silently change a checkpoint identity."""
    try:
        require(isinstance(raw,bytes) and 0<len(raw)<=65536)
        def pairs(items):
            result={}
            for key,value in items:
                require(key not in result);result[key]=value
            return result
        def constant(_):raise ManifestError('Checkpoint metadata denied')
        record=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=constant)
        digest=validate(record,expected_pins)
        return record,digest
    except ManifestError:raise
    except (ValueError,UnicodeError,TypeError,RecursionError):
        raise ManifestError('Checkpoint metadata denied') from None
