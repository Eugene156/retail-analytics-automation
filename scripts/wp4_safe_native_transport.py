"""N1 fixed command renderer/broker boundary. No default executor or subprocess."""
from dataclasses import dataclass,field
from hashlib import sha256
import json,re
import wp4_safe_fixture_contract as i1
import wp4_safe_fixture_planner as i2
from wp4_safe_native_manifest import NativeDenied,require,digest,binding,SECURITY_REVIEW_COMPLETE

HOST=('docker','--host','npipe:////./pipe/dockerDesktopLinuxEngine')
SQL_SETTINGS=b"SET ROLE g0_user;SET timezone='UTC';SET statement_timeout='120s';SET lock_timeout='5s';\n"
EMPTY_NONAUTH=('schema_migrations','source_snapshots','source_sheets','import_jobs','source_rows','invoice_lines',
              'quality_findings','report_cases','report_revisions','report_audit_events','owner_credentials','approval_policies')
BOOTSTRAP=b"CREATE ROLE postgres LOGIN SUPERUSER;ALTER ROLE g0_user NOLOGIN;CREATE DATABASE raa_wp2_validation OWNER g0_user;"
LOG_OPTIONS=('-c','listen_addresses=127.0.0.1','-c','unix_socket_directories=/run/n1',
    '-c','log_statement=none','-c','log_min_error_statement=panic','-c','log_min_duration_statement=-1',
    '-c','log_connections=off','-c','log_disconnections=off','-c','log_duration=off',
    '-c','shared_preload_libraries=','-c','session_preload_libraries=','-c','local_preload_libraries=')


@dataclass(frozen=True,repr=False)
class Command:
    operation:str
    argv:tuple
    payload:bytes=field(repr=False)
    context_sha256:str
    timeout:int=120
    def __repr__(self):return '<N1 Command: fixed argv; stdin redacted>'


@dataclass(frozen=True,repr=False)
class Reply:
    returncode:int
    stdout:bytes=field(repr=False)
    stderr:bytes=field(repr=False)
    approval_id:str
    provenance:str
    def __repr__(self):return '<N1 Reply: private>'


def psql(context,database=None,user='postgres'):
    target=dict(context.target_items);db=database or target['database']
    require(db in ('postgres','raa_wp2_validation',i2.reference_database(context) if context.purpose=='reference-build' else 'raa_wp2_validation'))
    require(user in ('postgres','g0_user'))
    return HOST+('exec','-i','--user','999:999',target['container'],'env','-i','PATH=/usr/local/bin:/usr/bin:/bin',
        'HOME=/nonexistent','LC_ALL=C','PGCONNECT_TIMEOUT=5','psql','-X','-w','-qAt','-v','ON_ERROR_STOP=1',
        '-v','VERBOSITY=sqlstate','-h','/run/n1','-U',user,'-d',db,'-f','-')


def seed(context,provider):
    require(type(provider) is i1.SyntheticSecrets);raw=provider.get(context,'owner-digest')
    require(re.fullmatch(b'[a-f0-9]{64}',raw))
    reviewer=i1.mappings(context.checkpoint_id)['fresh']['reviewer']
    return SQL_SETTINGS+("BEGIN;INSERT INTO retail.owner_credentials(singleton,reviewer_id,token_sha256) VALUES(true,'"+reviewer+"','"+raw.decode()+"');"
        "INSERT INTO retail.approval_policies(policy_version,reviewer_id,ttl_seconds) VALUES('local-publication-v1','"+reviewer+"',86400);COMMIT;").encode()


def render(context,inputs,operation,*,provider=None,table=None):
    context.checked();require(context.purpose in ('source-build','reference-build'));inputs.checked()
    target=dict(context.target_items);label='io.raa.safe-native='+context.checkpoint_id+':'+context.purpose
    argv=None;body=b'';timeout=120
    if operation=='readiness-info':argv=HOST+('info','--format','{{json .}}')
    elif operation=='readiness-ps':argv=HOST+('ps','-a','--format','{{.ID}}|{{.State}}')
    elif operation=='image-inspect':argv=HOST+('image','inspect',i1.POSTGRES_IMAGE)
    elif operation=='name-absence':
        argv=HOST+('ps','-a','--filter','name=^/'+target['container']+'$','--format','{{.ID}}')
    elif operation=='network-absence':argv=HOST+('network','ls','--filter','name=^'+target['network']+'$','--format','{{.Name}}')
    elif operation=='volume-absence':argv=HOST+('volume','ls','--filter','name=^'+target['volume']+'$','--format','{{.Name}}')
    elif operation=='network-create':argv=HOST+('network','create','--internal','--label',label,target['network'])
    elif operation=='volume-create':
        # Volatile build volumes only. Durable evidence is encrypted archive storage.
        argv=HOST+('volume','create','--driver','local','--opt','type=tmpfs','--opt','device=tmpfs',
                   '--opt','o=uid=999,gid=999,mode=0700,size=2147483648','--label',label,target['volume'])
    elif operation=='container-create':
        argv=HOST+('create','--pull','never','--name',target['container'],'--label',label,'--network',target['network'],
            '--user','999:999','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges=true',
            '--memory','2g','--cpus','2','--pids-limit','128','--tmpfs','/run/n1:rw,nosuid,nodev,noexec,uid=999,gid=999,mode=0700,size=64m',
            '--mount','type=volume,source='+target['volume']+',target=/var/lib/postgresql/data',
            '--entrypoint','sleep',i1.POSTGRES_IMAGE,'infinity')
    elif operation=='container-start':argv=HOST+('start',target['container'])
    elif operation in ('container-inspect','network-inspect','volume-inspect'):
        kind=operation.split('-')[0]
        argv=HOST+(('inspect',target[kind]) if kind=='container' else (kind,'inspect',target[kind]))
    elif operation=='initdb':argv=HOST+('exec','-i','--user','999:999',target['container'],'initdb','-D','/var/lib/postgresql/data',
        '--username=g0_user','--auth-local=trust','--auth-host=reject','--encoding=UTF8','--locale=C.UTF-8')
    elif operation=='postgres-start':
        argv=HOST+('exec','-i','--user','999:999',target['container'],'pg_ctl','-D','/var/lib/postgresql/data','-l','/run/n1/postgres.log',
            '-o',' '.join(LOG_OPTIONS),'-w','-t','30','start')
    elif operation=='bootstrap':argv=psql(context,'postgres','g0_user');body=BOOTSTRAP
    elif re.fullmatch('migration-[0-9]{3}',operation):
        number=int(operation[-3:]);require(1<=number<=(29 if context.purpose=='reference-build' else 20))
        argv=psql(context,i2.reference_database(context) if number>=22 else None)
        body=SQL_SETTINGS+i2.migration_batches(context,inputs)[number-1][1]
    elif operation=='public-import':
        import wp4_safe_fixture_recipe as files
        require(table is None)
        argv=psql(context);body=SQL_SETTINGS+b''.join(i2.import_chunks(context,inputs,files.public_rows(),i2.SHEETS));timeout=900
    elif operation=='report-alias':argv=psql(context);body=SQL_SETTINGS+i2.report_alias_sql(context,inputs)
    elif operation=='seed-owner':argv=psql(context);body=seed(context,provider)
    elif operation=='reference-rename':
        require(context.purpose=='reference-build');argv=psql(context,'postgres')
        db=i2.reference_database(context)
        body=("DO $guard$ BEGIN IF EXISTS(SELECT 1 FROM pg_database WHERE datname='"+db+"') OR "
              "EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname='raa_wp2_validation') OR EXISTS(SELECT 1 FROM pg_prepared_xacts) "
              "THEN RAISE EXCEPTION 'N1 reference rename denied';END IF;END $guard$;ALTER DATABASE raa_wp2_validation RENAME TO "+db+';').encode()
    elif operation in ('fence','capture'):
        db='raa_wp2_validation' if context.purpose=='source-build' else i2.reference_database(context)
        if operation=='fence':
            argv=psql(context,'postgres');body=("DO $f$ BEGIN IF EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname='"+db+"') "
                "OR EXISTS(SELECT 1 FROM pg_prepared_xacts) THEN RAISE EXCEPTION 'N1 capture drain denied';END IF;END $f$;"
                "REVOKE CONNECT ON DATABASE "+db+" FROM PUBLIC;ALTER DATABASE "+db+' CONNECTION LIMIT 0;').encode()
        else:argv=HOST+('exec','-i','--user','999:999',target['container'],'pg_dump','-h','/run/n1','-U','postgres',
                       '-d',db,'--format=custom','--schema=retail','--no-password');timeout=900
    elif operation in ('tables','sequences','catalog','roles','memberships','identity','migrations','source-counts','report','authority','row-hashes','sequence-value','runtime-guard'):
        db='raa_wp2_validation' if context.purpose=='source-build' else i2.reference_database(context)
        if operation=='runtime-guard':db='postgres'
        argv=psql(context,db);body=SQL_SETTINGS+observation_sql(context,operation,table).encode();timeout=900 if operation=='row-hashes' else 120
    require(argv is not None)
    return Command(operation,argv,body,sha256(i1.canonical(binding(context,inputs))).hexdigest(),timeout)


def observation_sql(context,operation,table=None):
    operation={'source-counts':'source_counts','runtime-guard':'runtime_guard'}.get(operation,operation)
    # Catalog queries copied from existing helper as SQL, never its live transport.
    if operation=='catalog':
        import ast
        from pathlib import Path
        source=Path(__file__).with_name('wp4_checkpoint_local.py').read_text(encoding='utf-8')
        tree=ast.parse(source);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='fingerprint')
        assignment=next(n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='catalog' for t in n.targets))
        template=assignment.value.args[2].left.value
        return template%(('retail',)*7)+';'
    queries=dict(tables="SELECT coalesce(json_agg(tablename ORDER BY tablename),'[]') FROM pg_tables WHERE schemaname='retail'",
        sequences="SELECT coalesce(json_agg(sequencename ORDER BY sequencename),'[]') FROM pg_sequences WHERE schemaname='retail'",
        roles="SELECT json_agg(json_build_object('name',rolname,'login',rolcanlogin,'superuser',rolsuper,'createdb',rolcreatedb,'createrole',rolcreaterole,'replication',rolreplication,'bypassrls',rolbypassrls) ORDER BY rolname) FROM pg_roles WHERE rolname='g0_user' OR rolname='postgres' OR rolname LIKE 'raa\\_%' ESCAPE '\\'",
        memberships="SELECT coalesce(json_agg(json_build_array(roleid,member)),'[]') FROM pg_auth_members",
        identity="SELECT json_build_object('system_identifier',(SELECT system_identifier::text FROM pg_control_system()),'database_oid',(SELECT oid FROM pg_database WHERE datname=current_database()),'database',current_database())",
        migrations="SELECT json_agg(version ORDER BY version) FROM retail.schema_migrations",
        source_counts="SELECT json_build_array((SELECT count(*) FROM retail.source_rows WHERE worksheet='Year 2009-2010'),(SELECT count(*) FROM retail.source_rows WHERE worksheet='Year 2010-2011'),(SELECT count(*) FROM retail.source_rows))",
        runtime_guard="SELECT json_build_object('host_reject',NOT EXISTS(SELECT 1 FROM pg_hba_file_rules WHERE type<>'local' AND auth_method<>'reject') AND NOT EXISTS(SELECT 1 FROM pg_hba_file_rules WHERE error IS NOT NULL),'loopback',current_setting('listen_addresses')='127.0.0.1','no_extensions',NOT EXISTS(SELECT 1 FROM pg_extension WHERE extname<>'plpgsql') AND NOT EXISTS(SELECT 1 FROM pg_language WHERE lanname NOT IN('internal','c','sql','plpgsql')) AND NOT EXISTS(SELECT 1 FROM pg_foreign_server),'no_preload',current_setting('shared_preload_libraries')='' AND current_setting('session_preload_libraries')='' AND current_setting('local_preload_libraries')='','nolog',current_setting('log_statement')='none' AND current_setting('log_min_error_statement')='panic')")
    if operation in queries:return queries[operation]+';'
    if operation in ('row-hashes','sequence-value'):
        require(type(table) is str and re.fullmatch('[a-z][a-z0-9_]{0,100}',table))
        if operation=='row-hashes':return "COPY (SELECT h FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') AS h FROM retail.\""+table+'\" t) r ORDER BY h COLLATE "C") TO STDOUT;'
        return 'SELECT json_build_array(last_value,is_called) FROM retail."'+table+'";'
    if operation=='report':
        source=i1.SOURCE['workbook_sha256'].upper()
        return ("SELECT json_build_object('case_id',case_id,'revision',revision,'bytes',octet_length(payload_text),'sha256',encode(sha256(convert_to(payload_text,'UTF8')),'hex')) FROM retail.report_revisions WHERE case_id='"+i1.LEGACY_CASE+"' AND revision=1;"
            "SET ROLE raa_wp2_api;SELECT json_build_object('scoped_comparison_sha256',encode(sha256(convert_to(retail.api_comparison_report_v1('"+source+"','2011-01-28 09:00:00','2011-01-28 10:00:00','2011-01-28 10:00:00'),'UTF8')),'hex'));"
            "SET ROLE raa_wp2_case_api;SELECT json_build_object('scoped_revision_sha256',encode(sha256(convert_to(retail.api_get_revision_v1('"+i1.LEGACY_CASE+"',1),'UTF8')),'hex'));")
    if operation=='authority':
        return "SELECT json_build_object('owner_count',(SELECT count(*) FROM retail.owner_credentials WHERE revoked_at IS NULL),'policy_count',(SELECT count(*) FROM retail.approval_policies),'reviewer_id',(SELECT reviewer_id FROM retail.owner_credentials),'ttl_seconds',(SELECT ttl_seconds FROM retail.approval_policies));"
    raise NativeDenied()


class Transport:
    """Trusted human-approval broker executes one validated command at a time.

Broker implements approve_and_execute(Command)->Reply; has no silent executor,
environment or legacy fallback. It must implement per-command require_escalated.
"""
    def __init__(self,context,inputs,broker=None,provider=None):
        context.checked();inputs.checked();self.context=context;self.inputs=inputs;self.broker=broker
        self.provider=provider;self._lost=False;self._approvals=set();self._tables=set();self._sequences=set()
    def __repr__(self):return '<N1 Transport: approved fixed commands only>'
    def call(self,operation,*,table=None):
        try:
            require(not self._lost and self.broker is not None)
            require(self.broker.provenance=='offline-double' or SECURITY_REVIEW_COMPLETE)
            if operation=='row-hashes':require(table in self._tables)
            if operation=='sequence-value':require(table in self._sequences)
            command=render(self.context,self.inputs,operation,provider=self.provider,table=table)
            result=self.broker.approve_and_execute(command)
            require(type(result) is Reply and type(result.returncode) is int and result.returncode==0)
            require(type(result.stdout) is bytes and len(result.stdout)<=536870912 and type(result.stderr) is bytes and len(result.stderr)<=1048576)
            require(type(result.approval_id) is str and re.fullmatch('[a-f0-9]{32}',result.approval_id) and result.approval_id not in self._approvals)
            require(result.provenance in ('offline-double','native-approved-broker'));self._approvals.add(result.approval_id)
            if self.provider is not None:
                self.provider.check_capture(self.context,result.stderr)
                if operation!='capture':
                    tail=b''
                    for index in range(0,len(result.stdout),65536):
                        chunk=tail+result.stdout[index:index+65536];self.provider.check_capture(self.context,chunk);tail=chunk[-256:]
            if operation in ('tables','sequences'):
                names=json.loads(result.stdout);require(type(names) is list and len(names)==len(set(names))
                    and all(type(n) is str and re.fullmatch('[a-z][a-z0-9_]{0,100}',n) for n in names))
                if operation=='tables':self._tables=set(names)
                else:self._sequences=set(names)
            return result
        except Exception:self._lost=True;raise NativeDenied() from None
    def command(self,*args,**kwargs):raise NativeDenied()
    def connect(self,*args,**kwargs):raise NativeDenied()
