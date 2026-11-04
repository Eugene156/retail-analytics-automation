"""I2 deterministic SQL generation and capture planning. Never executes a plan.

Repository/public inputs are explicit bytes; this module performs no filesystem,
environment, socket, subprocess, credential minting or native evidence acquisition.
"""
from dataclasses import dataclass
from hashlib import sha256
import csv
import io
import json
import re

import wp4_safe_fixture_contract as i1

VERSION='wp4-safe-fixture-recipe-I2-v1'
SHEETS=(('Year 2009-2010',525461),('Year 2010-2011',541910))
HEADERS=('Invoice','StockCode','Description','Quantity','InvoiceDate','Price','Customer ID','Country')
EMPTY=('owner_portal_sessions','owner_portal_events','approval_proposals','approval_requests_v2',
       'approval_request_events_v2','proposal_audit_events','review_decisions_v1','review_decision_events_v1','publication_outbox_v1')


class PlannerDenied(Exception):
    def __init__(self):super().__init__('I2 offline planner denied')


def require(value):
    if not value:raise PlannerDenied()


@dataclass(frozen=True)
class Inputs:
    migrations:tuple
    finalize:bytes

    def checked(self):
        require(type(self.migrations) is tuple and len(self.migrations)==29)
        for n,item in enumerate(self.migrations,1):
            require(type(item) is tuple and len(item)==2)
            name,body=item
            require(type(name) is str and re.fullmatch(f'{n:03d}_[a-z0-9_]+\\.sql',name))
            require(type(body) is bytes and 0<len(body)<=262144 and b'\r' not in body)
            try:body.decode('utf-8')
            except UnicodeError:raise PlannerDenied() from None
        require(type(self.finalize) is bytes and 0<len(self.finalize)<=262144 and b'\r' not in self.finalize)
        try:self.finalize.decode('utf-8')
        except UnicodeError:raise PlannerDenied() from None
        return self

    def hashes(self):
        self.checked()
        return {**{name:sha256(body).hexdigest() for name,body in self.migrations},
                'import_finalize.sql':sha256(self.finalize).hexdigest()}


def checked(context,inputs):
    require(type(context) is i1.ScopedContext and context.purpose in ('source-build','reference-build'))
    context.checked();require(type(inputs) is Inputs);inputs.checked()


def reference_database(context):
    context.checked();require(context.purpose=='reference-build')
    return 'raa_wp4_dispatch_test_'+i1.derived(context.checkpoint_id,'reference-build').replace('-','')[:12]


def recipe(context,inputs):
    checked(context,inputs)
    source=dict(i1.SOURCE)
    steps=['verify-fresh-ownership-isolation-no-secret-fallback','apply-001-020-verbatim',
           'import-public-physical-rows','classify-and-quality-v1','native-report-alias-and-scoped-API-parity',
           'seed-private-synthetic-owner-policy','verify-g0-ownership-NOLOGIN-roles-no-memberships']
    if context.purpose=='reference-build':steps+=['apply-021-verbatim','disconnect-and-guarded-reference-rename','apply-022-029-verbatim']
    steps+=['verify-empty-execution-authority','drain-and-fence-owned-build','native-fingerprints-before-capture',
            'custom-archive-capture','native-fingerprints-after-capture','retain-private-artifacts-and-seal-manifest']
    return dict(version=VERSION,stage='offline-I2',checkpoint_id=context.checkpoint_id,purpose=context.purpose,
        I1_contract_sha256=context.contract_sha256,source=source,postgresql_image=i1.POSTGRES_IMAGE,
        inputs=inputs.hashes(),mapping=i1.mappings(context.checkpoint_id),target_reservation=dict(context.target_items),
        reference_database_after_021=reference_database(context) if context.purpose=='reference-build' else None,
        steps=[dict(index=n,action=name,status='not-run') for n,name in enumerate(steps,1)],
        authority_inventory=dict(owner_credentials_planned=1,approval_policies_planned=1,ttl_seconds=86400,
                                 empty_tables=list(EMPTY),native_observed=False),
        required_native_observations=['full-resource-IDs-and-name-absence','isolation-egress-dispatch-denials',
            'source-row-counts-FKs-quality','actual-4129-report-hash-and-API-equality','exact-owner-and-policy',
            'real-independent-main020-UAT029-catalog-ACL-sequences','zero-clients-and-prepared-work',
            'capture-fence-and-pre/post-preservation','fresh-quarantine-restore'],
        native_evidence_acquired=False,materialization_allowed=False,external_dispatch_allowed=False,
        application_writers_admitted=False,blocked_gates=list(i1.GATES))


def validate_recipe(raw,context,inputs):
    require(type(raw) is bytes and len(raw)<=32768)
    require(raw==i1.canonical(recipe(context,inputs)))
    return sha256(raw).hexdigest()


def migration_batches(context,inputs):
    """Keep complete guarded migration bodies; DB transition is a separate step."""
    checked(context,inputs)
    count=29 if context.purpose=='reference-build' else 20
    return tuple((name,b'BEGIN;SET LOCAL timezone=\'UTC\';\n'+body+b'\nCOMMIT;\n')
                 for name,body in inputs.migrations[:count])


def csv_row(values):
    stream=io.StringIO(newline='');csv.writer(stream,lineterminator='\n').writerow(values)
    return stream.getvalue().encode('utf-8')


def import_chunks(context,inputs,rows,counts=SHEETS):
    """Data-only COPY encoding; no literal untrusted cells in SQL statements.

    Production caller must supply authenticated public rows; generator additionally
    enforces complete worksheet order/physical identities. Tests use small counts.
    """
    checked(context,inputs)
    require(counts==SHEETS)  # Tiny tests patch the module constant, not a live override.
    source=i1.SOURCE['workbook_sha256'].upper();mapping=i1.mappings(context.checkpoint_id)
    yield b"BEGIN;SET LOCAL timezone='UTC';\n"
    yield b'CREATE TEMP TABLE stage_snapshot (source_file_sha256 text,dataset_id text,source_filename text,source_bytes bigint,source_url text,license_name text,expected_data_rows bigint) ON COMMIT DROP;\nCOPY stage_snapshot FROM STDIN WITH (FORMAT csv);\n'
    yield csv_row((source,'UCI-502','online_retail_II.xlsx',45622278,'https://archive.ics.uci.edu/dataset/502/online+retail+ii','CC BY 4.0',sum(n for _,n in counts)))
    yield b'\\.\nCREATE TEMP TABLE stage_sheets (source_file_sha256 text,worksheet text,sheet_ordinal integer,original_headers jsonb,expected_data_rows bigint) ON COMMIT DROP;\nCOPY stage_sheets FROM STDIN WITH (FORMAT csv);\n'
    for ordinal,(name,count) in enumerate(counts,1):yield csv_row((source,name,ordinal,json.dumps(HEADERS,separators=(',',':')),count))
    yield b'\\.\nCREATE TEMP TABLE stage_job (job_id uuid,idempotency_key text) ON COMMIT DROP;\nCOPY stage_job FROM STDIN WITH (FORMAT csv);\n'
    yield csv_row((mapping['fresh']['import-job'],'fixture_'+context.checkpoint_id.replace('-','')))
    yield b'\\.\nCREATE TEMP TABLE stage_rows (source_file_sha256 text,worksheet text,source_row_number integer,raw_cells jsonb) ON COMMIT DROP;\nCOPY stage_rows FROM STDIN WITH (FORMAT csv);\n'
    iterator=iter(rows)
    for sheet,count in counts:
        for ordinal in range(2,count+2):
            try:item=next(iterator)
            except StopIteration:raise PlannerDenied() from None
            require(type(item) in (list,tuple) and len(item)==3)
            name,row,cells=item
            require(type(name) is str and name==sheet and type(row) is int and row==ordinal)
            require(type(cells) in (list,tuple) and len(cells)==8)
            require(all(type(cell) in (list,tuple) and len(cell)==2 and all(type(v) is str for v in cell) for cell in cells))
            payload=json.dumps(cells,ensure_ascii=True,separators=(',',':'),allow_nan=False)
            require(len(payload)<=65536)
            yield csv_row((source,name,row,payload))
    sentinel=object();require(next(iterator,sentinel) is sentinel)
    yield b'\\.\n'+inputs.finalize+b'\nCOMMIT;\n'
    yield ("BEGIN;SET LOCAL timezone='UTC';SELECT * FROM retail.classify_snapshot_v1('"+source+"');COMMIT;\n").encode()


def report_alias_sql(context,inputs):
    """Generate only public report alias; owner secrets are never rendered."""
    checked(context,inputs);alias=i1.LEGACY_CASE;source=i1.SOURCE['workbook_sha256'].upper()
    identity=dict(contract_version='report-request-v1',source_file_sha256=source,policy_version='v1',
        report_schema_version='deterministic-comparison-report-v1',source_time_interpretation='Europe/London-assumed',
        period_start_inclusive='2011-01-28T09:00:00.000000',period_end_exclusive='2011-01-28T10:00:00.000000',source_as_of_exclusive='2011-01-28T10:00:00.000000')
    data=json.dumps(identity,separators=(',',':'))  # fixed public keys/values only
    return ("BEGIN;SET LOCAL timezone='UTC';INSERT INTO retail.report_cases(case_id,idempotency_key,request_identity) VALUES('"+alias+"','fixture_"+context.checkpoint_id.replace('-','')+"','"+data+"');\n"
        "INSERT INTO retail.report_audit_events(case_id,event_type) VALUES('"+alias+"','request_received');\n"
        "SELECT retail.api_finish_report_v1('"+alias+"');\nDO $parity$ DECLARE body text; BEGIN "
        "SELECT payload_text INTO STRICT body FROM retail.report_revisions WHERE case_id='"+alias+"' AND revision=1;"
        "IF octet_length(body)<>4129 OR encode(sha256(convert_to(body,'UTF8')),'hex')<>'"+i1.SOURCE['report_sha256']+"' "
        "OR body IS DISTINCT FROM retail.api_comparison_report_v1('"+source+"','2011-01-28 09:00:00','2011-01-28 10:00:00','2011-01-28 10:00:00') "
        "OR body IS DISTINCT FROM retail.api_get_revision_v1('"+alias+"',1) THEN RAISE EXCEPTION 'I2 report parity denied';END IF;END $parity$;COMMIT;\n").encode('ascii')


class CapturePlanner:
    """Immutable planned acquisition list, not a native state machine/receipt."""
    def __init__(self,context,inputs):
        self._raw=i1.canonical(recipe(context,inputs))
    def document(self):return self._raw
    def execute(self):raise PlannerDenied()
    def accept_native_evidence(self,value):raise PlannerDenied()
    def __repr__(self):return '<CapturePlanner: offline non-admitting>'
