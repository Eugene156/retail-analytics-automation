"""N1 private native binding contract. Structural claims never authorize restore."""
from hashlib import sha256
import json,re
import wp4_safe_fixture_contract as i1
import wp4_safe_fixture_planner as i2

VERSION='wp4-safe-private-native-capture-N1-v1'
# Review found incomplete catalog/ACL/fence bindings. No native seal may be
# produced until a separately reviewed completion removes this source-code gate.
SECURITY_REVIEW_COMPLETE=False


class NativeDenied(Exception):
    def __init__(self):super().__init__('N1 fixture boundary denied')


def require(value):
    if not value:raise NativeDenied()


def digest(value):return type(value) is str and re.fullmatch('[a-f0-9]{64}',value) is not None


def binding(context,inputs):
    require(type(context) is i1.ScopedContext);context.checked();inputs.checked()
    return dict(checkpoint_id=context.checkpoint_id,purpose=context.purpose,
        I1_contract_sha256=context.contract_sha256,I2_recipe_sha256=sha256(i1.canonical(i2.recipe(context,inputs))).hexdigest(),
        source=dict(i1.SOURCE),image=i1.POSTGRES_IMAGE,mapping=i1.mappings(context.checkpoint_id))


def validate_fingerprint(value):
    # Preliminary structural parser only. Not a complete catalog/ACL validator;
    # record/validate are gated off until the expert's inventory findings close.
    require(type(value) is dict and set(value)=={'catalog','rows','sequences','roles','memberships','authority','identity','migrations','source_counts','report'})
    require(type(value['catalog']) is dict and set(value['catalog'])=={'schema','relations','columns','functions','constraints','indexes','triggers'})
    require(all(type(v) in (list,dict) for v in value['catalog'].values()))
    for key in ('rows','sequences'):require(type(value[key]) is dict)
    require(bool(value['rows']) and all(re.fullmatch('[a-z][a-z0-9_]{0,100}',k) and type(v) is dict
        and set(v)=={'count','sha256'} and type(v['count']) is int and v['count']>=0 and digest(v['sha256']) for k,v in value['rows'].items()))
    require(value['rows'].get('source_rows',{}).get('count')==1067371 and value['rows'].get('owner_credentials',{}).get('count')==1
        and value['rows'].get('approval_policies',{}).get('count')==1)
    require(all(re.fullmatch('[a-z][a-z0-9_]{0,100}',k) and type(v) is list and len(v)==2
        and type(v[0]) is int and type(v[1]) is bool for k,v in value['sequences'].items()))
    require(type(value['roles']) is list and bool(value['roles']) and type(value['memberships']) is list and not value['memberships'])
    for row in value['roles']:
        require(type(row) is dict and set(row)=={'name','login','superuser','createdb','createrole','replication','bypassrls'})
        require(type(row['name']) is str and re.fullmatch('[a-z][a-z0-9_]{0,100}',row['name']))
        require(all(type(row[k]) is bool for k in row if k!='name'))
        require(not row['login'] or row['name']=='postgres')
        require(row['name'] in ('postgres','g0_user') or not any(row[k] for k in ('superuser','createdb','createrole','replication','bypassrls')))
    require(len({r['name'] for r in value['roles']})==len(value['roles']) and any(r['name']=='g0_user' and not r['login'] for r in value['roles']))
    require(type(value['authority']) is dict and set(value['authority'])=={'owner_count','policy_count','reviewer_id','ttl_seconds','empty_tables'})
    a=value['authority'];require(type(a['owner_count']) is int and a['owner_count']==1 and type(a['policy_count']) is int and a['policy_count']==1)
    i1.identity(a['reviewer_id']);require(type(a['ttl_seconds']) is int and a['ttl_seconds']==86400)
    require(type(a['empty_tables']) is dict and bool(a['empty_tables']) and all(type(v) is int and v==0 for v in a['empty_tables'].values()))
    identity=value['identity'];require(type(identity) is dict and set(identity)=={'system_identifier','database_oid','database'})
    require(type(identity['system_identifier']) is str and re.fullmatch('[0-9]{10,20}',identity['system_identifier']))
    require(type(identity['database_oid']) is int and identity['database_oid']>0 and type(identity['database']) is str)
    require(type(value['migrations']) is list and all(type(v) is int for v in value['migrations']))
    require(value['source_counts']==[525461,541910,1067371])
    require(value['report']==dict(case_id=i1.LEGACY_CASE,revision=1,bytes=4129,sha256=i1.SOURCE['report_sha256'],scoped_API_equal=True))
    return value


def record(contexts,inputs,facts,artifacts):
    """Bound captured-unrestored claims only; call only after actual materializer."""
    require(SECURITY_REVIEW_COMPLETE)
    require(set(contexts)==set(facts)=={'source-build','reference-build'})
    require(type(artifacts) is dict and set(artifacts)=={'source-archive','reference-archive','source-before','source-after','reference-before','reference-after'})
    for entry in artifacts.values():require(type(entry) is dict and set(entry)=={'bytes','sha256'} and type(entry['bytes']) is int and entry['bytes']>0 and digest(entry['sha256']))
    bindings={}
    systems=set()
    for purpose,context in contexts.items():
        context.checked();require(context.purpose==purpose);bindings[purpose]=binding(context,inputs)
        pair=facts[purpose];require(type(pair) is dict and set(pair)=={'before','after','resources'})
        before=validate_fingerprint(pair['before']);require(pair['before']==pair['after'])
        require(before['migrations']==list(range(1,21 if purpose=='source-build' else 30)))
        require(before['authority']['reviewer_id']==i1.mappings(context.checkpoint_id)['fresh']['reviewer'])
        require(before['identity']['database']==('raa_wp2_validation' if purpose=='source-build' else i2.reference_database(context)))
        resource=pair['resources'];require(type(resource) is dict and set(resource)=={'container_id','network_id','volume','isolation_verified','fence_verified'})
        require(digest(resource['container_id']) and digest(resource['network_id']) and resource['volume']==dict(context.target_items)['volume'])
        require(resource['isolation_verified'] is True and resource['fence_verified'] is True)
        systems.add(before['identity']['system_identifier'])
    require(len(systems)==2 and len({c.checkpoint_id for c in contexts.values()})==1)
    return dict(version=VERSION,profile='private-synthetic-authority-captured-unrestored',bindings=bindings,
        facts=facts,artifacts=artifacts,authority_bearing=True,restore_admitted=False,rehearsal_admitted=False,
        application_writers_admitted=False,external_dispatch_allowed=False,blocked_gates=list(i1.GATES),
        evidence_class='structural-native-claims-require-independent-verification')


def validate(raw,contexts,inputs):
    try:
        require(type(raw) is bytes and 0<len(raw)<=16777216);value=json.loads(raw)
        expected=record(contexts,inputs,value['facts'],value['artifacts']);require(raw==i1.canonical(expected));return expected
    except Exception:raise NativeDenied() from None
