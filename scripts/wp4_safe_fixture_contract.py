"""I1-only pure metadata/context/secret boundary. No native admission or I/O.

This distinct offline contract cannot authorize materialization or restoration.
Synthetic secret values are explicitly supplied in memory; never minted/read.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import UUID, uuid5

VERSION='wp4-synthetic-native-fixture-I1-v1'
PROFILE='private-public-data-synthetic-authority'
POSTGRES_IMAGE='postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652'
NAMESPACE=UUID('62e3d5e8-b870-5f26-bf7f-1ed8c12f0165')
PUBLIC_CHECKPOINT='f65427b5-fa0a-5299-b3a5-98d61d8296c2'
PUBLIC_CASE='2b451b8d-b543-586c-b2a0-bac51203f320'
LEGACY_CASE='61b10574-c842-4dae-8e8b-647f0d51ba55'
ORIGINAL_CHECKPOINT='15c54349-163b-42ca-8ddd-b148a6ae8984'
SOURCE=dict(checkpoint_id=PUBLIC_CHECKPOINT,
    manifest_sha256='41fbcb2f1028898d06faa10fba1cd5274712378efa73fa50f639812611ea1f1d',
    workbook_sha256='bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980',
    report_sha256='2e913def90e1a5e41f9ac6009dd49b7411a8e703d936cdc6b7e5f7a95ed12b07',report_bytes=4129)
GATES=('positive-source-restart-fence','old-application-session-drain','restore-authority-and-xid-quarantine',
       'future-creator-default-and-effective-privileges','admitted-business-transaction-drain',
       'OPEN-main-runtime-and-n8n-writer-admission','general-PID-reuse-safe-termination','full-physical-storage-integrity')
SECRET_NAMES=('bootstrap-password','owner-token','owner-digest','controller-password','observer-password')


class FixtureDenied(Exception):
    """One finite category; supplied values are never interpolated."""
    def __init__(self):super().__init__('I1 fixture boundary denied')


def require(value):
    if not value:raise FixtureDenied()


def canonical(value):
    try:return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)+'\n').encode('ascii')
    except (TypeError,ValueError,UnicodeError):raise FixtureDenied() from None


def identity(value):
    require(type(value) is str)
    try:parsed=UUID(value)
    except (ValueError,AttributeError):raise FixtureDenied() from None
    require(str(parsed)==value and parsed.int!=0 and parsed.version in (4,5))
    return value


def derived(checkpoint,kind):return str(uuid5(NAMESPACE,identity(checkpoint)+':'+kind))


def mappings(checkpoint):
    identity(checkpoint)
    fresh={kind:derived(checkpoint,kind) for kind in ('reviewer','import-job','source-build','reference-build','rehearsal')}
    require(len(set(fresh.values()))==len(fresh) and checkpoint not in fresh.values())
    require(not ({checkpoint,*fresh.values()} & {PUBLIC_CHECKPOINT,PUBLIC_CASE,LEGACY_CASE,ORIGINAL_CHECKPOINT}))
    return dict(fresh=fresh,report=dict(logical_case_id=PUBLIC_CASE,isolated_legacy_alias=LEGACY_CASE,
        revision=1,alias_scope_checkpoint=checkpoint,report_sha256=SOURCE['report_sha256'],report_bytes=4129))


def targets(checkpoint):
    result={}
    for kind in ('source-build','reference-build','rehearsal'):
        key=derived(checkpoint,kind).replace('-','')
        # Full UUID suffix avoids truncation collisions. Actual resource absence/
        # IDs/labels/network/ports remain separate native checks, not these names.
        prefix='raa-fixture-'+key
        result[kind]=dict(container=prefix+'-postgres',network=prefix+'-internal',volume=prefix+'-data',
            database=('raa_wp2_validation' if kind in ('source-build','reference-build') else 'raa_fixture_'+key),
            native_binding='not-implemented-I3',isolation_observed=False,external_dispatch_allowed=False)
    return result


def proposal(checkpoint):
    """Deterministic non-secret scaffold only; no fresh UUID/secret creation."""
    mapping=mappings(checkpoint)
    return dict(contract_version=VERSION,profile=PROFILE,stage='offline-I1',checkpoint_id=checkpoint,postgresql_image=POSTGRES_IMAGE,
        source=dict(SOURCE),identity_mapping=mapping,targets=targets(checkpoint),
        materialization_recipe=dict(status='not-implemented-I2',sha256=None),
        authority_policy=dict(seed_status='not-created',synthetic_owner_count_planned=1,ttl_seconds=86400,
            sessions=0,requests=0,decisions=0,outbox=0),
        native_evidence=dict(archive='not-captured',catalog='not-observed',restore='not-run',source_fence='not-observed'),
        application_writers_admitted=False,external_dispatch_allowed=False,blocked_gates=list(GATES))


@dataclass(frozen=True)
class ScopedContext:
    checkpoint_id:str
    contract_sha256:str
    purpose:str
    target_items:tuple

    @classmethod
    def from_contract(cls,raw,purpose):
        record=validate(raw)
        require(type(purpose) is str and purpose in record['targets'])
        return cls(record['checkpoint_id'],sha256(raw).hexdigest(),purpose,tuple(sorted(record['targets'][purpose].items())))

    def checked(self):
        # Revalidate even direct dataclass construction; no forged external path.
        expected=proposal(self.checkpoint_id)
        require(type(self.purpose) is str and self.purpose in expected['targets'])
        require(self.contract_sha256==sha256(canonical(expected)).hexdigest())
        require(self.target_items==tuple(sorted(expected['targets'][self.purpose].items())))
        require(type(self.target_items) is tuple and all(type(item) is tuple and len(item)==2
            and type(item[0]) is str and type(item[1]) is type(expected['targets'][self.purpose][item[0]]) for item in self.target_items))
        return self

    def request(self,kind,value):
        """Validate declared resource identity only; never open/operate it."""
        self.checked()
        require(type(kind) is str and kind in ('container','network','volume','database'))
        require(type(value) is str and value==dict(self.target_items)[kind])
        return value

    def admit_native(self):
        self.checked();raise FixtureDenied()


def validate(raw):
    require(type(raw) is bytes and 0<len(raw)<=16384)
    try:
        record=json.loads(raw)
        require(type(record) is dict and type(record.get('checkpoint_id')) is str)
        expected=proposal(record['checkpoint_id'])
        # Exact bytes exclude duplicate keys, bool/int substitution, surplus
        # fields, embedded authority/artifact data and encoded hidden metadata.
        require(raw==canonical(expected))
        return expected
    except FixtureDenied:raise
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):raise FixtureDenied() from None


class SyntheticSecrets:
    """In-memory, context-bound registry; no env/file/default/live fallback.

    Does not assert caller-supplied bytes have no production origin. The explicit
    injection boundary and future native secret minting must establish provenance.
    Offline tests use nonfunctional dummy values only.
    """
    __slots__=('_context','_values','_capture_values','_closed')

    def __init__(self,context,values):
        require(type(context) is ScopedContext);context.checked()
        require(type(values) is dict and set(values)<=set(SECRET_NAMES))
        require(all(type(v) is bytes and 16<=len(v)<=256 and all(33<=b<=126 for b in v) for v in values.values()))
        require(len(set(values.values()))==len(values))
        # Digest is itself SQL authority: protect it even when not explicitly
        # registered. This does not make a missing get(owner-digest) succeed.
        token_digest=sha256(values['owner-token']).hexdigest().encode('ascii') if 'owner-token' in values else None
        if token_digest is not None and 'owner-digest' in values:require(values['owner-digest']==token_digest)
        self._context=context;self._values=dict(values);self._closed=False
        self._capture_values=tuple(values.values())+((token_digest,) if token_digest is not None else ())

    def __repr__(self):return '<SyntheticSecrets: redacted>'
    def __reduce_ex__(self,protocol):raise FixtureDenied()

    def _check(self,context):
        require(type(context) is ScopedContext);context.checked()
        require(not self._closed and context==self._context)

    def get(self,context,name):
        self._check(context)
        require(type(name) is str and name in SECRET_NAMES and name in self._values)
        return self._values[name]

    def check_capture(self,context,data):
        self._check(context)
        require(bool(self._values))
        require(type(data) is bytes and len(data)<=1048576)
        require(b'SCRAM-SHA-256$' not in data and not any(value in data for value in self._capture_values))
        return None

    def close(self):
        self._values.clear();self._capture_values=();self._closed=True
        # Logical disposal only: Python immutable bytes cannot guarantee erasure.
