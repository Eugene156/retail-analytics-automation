"""Fixed isolated logical backup/restore operations; no main lifecycle controls."""
from hashlib import sha256
import json
import re
import secrets
import subprocess
from uuid import uuid4
from wp3_n8n_local import invoke,expect,ROOT
from wp4_portal_local import retain

DATABASE=re.compile(r'raa_wp4_dispatch_test_[a-f0-9]{12}')
ROLE=re.compile(r'raa_wp4_(?:portal|dispatch)_test_[a-f0-9]{12}')
PG_PREFIX='raa-wp4-recovery-postgres-'
LABEL='wp4-recovery-postgres'
SIGNATURES=('retail.api_portal_attempt_state_v1(uuid,text)',
 'retail.api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text)',
 'retail.api_accept_portal_attempt_v1(uuid,text,uuid,text)',
 'retail.api_report_portal_attempt_v1(uuid,text,uuid,text,text)',
 'retail.api_reconcile_portal_attempt_v1(uuid,text)')


def test_database(value):
    expect(isinstance(value,str) and DATABASE.fullmatch(value) is not None,'generated-recovery-database')
    return value


def owned_pg(container):
    expect(re.fullmatch(PG_PREFIX+r'[a-f0-9]{12}',container) is not None,'exact-recovery-PG-name')
    expect(invoke(['inspect',container,'--format','{{index .Config.Labels "io.raa.test-scope"}}']).stdout.strip()==LABEL,'owned-recovery-PG-label')


def query(container,database,value):
    test_database(database)
    return invoke(['exec','-i',container,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','g0_user','-d',database,'-f','-'],value).stdout.strip()


def roles(container,database):
    # ACL identities only: passwords/login properties/owner tokens never exported.
    raw=query(container,database,"BEGIN READ ONLY; SELECT DISTINCT r.rolname FROM pg_roles r WHERE r.oid IN ("
      "SELECT a.grantee FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE n.nspname='retail' "
      "UNION SELECT a.grantee FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(c.relacl) a WHERE n.nspname='retail' "
      "UNION SELECT a.grantee FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a WHERE n.nspname='retail') ORDER BY 1; COMMIT;")
    result=raw.splitlines()
    expect(all(n=='g0_user' or re.fullmatch(r'raa_[a-z0-9_]{1,80}',n) for n in result),'bounded-project-ACL-roles')
    return result


def binary(arguments,path,restore=False,allow_failure=False):
    # Backup bytes/digests are sensitive. Never route dump or stderr to invoke/stdout.
    target=path.resolve();base=(ROOT/'.local'/'wp4-recovery').resolve()
    expect(target.is_relative_to(base),'private-backup-path')
    with path.open('rb' if restore else 'xb') as stream:
        result=subprocess.run(['docker',*arguments],stdin=stream if restore else None,
           stdout=subprocess.PIPE if restore else stream,stderr=subprocess.PIPE,check=False,timeout=120)
    if not allow_failure:expect(result.returncode==0,'private-restore' if restore else 'private-backup')
    return result.returncode


def backup(container,database,path):
    test_database(database)
    binary(['exec',container,'pg_dump','-U','g0_user','-d',database,'--format=custom','--no-owner','--schema=retail'],path)
    data=path.read_bytes();expect(len(data)>128 and data[:5]==b'PGDMP','custom-backup-format')
    return {'bytes':len(data),'sha256':sha256(data).hexdigest()}


def restore(container,database,path,identities):
    owned_pg(container);test_database(database)
    for name in identities:
        expect(name=='g0_user' or re.fullmatch(r'raa_[a-z0-9_]{1,80}',name),'bounded-restore-role')
    # Global identities restored DISABLED. No old credential/membership travels.
    role_sql='\n'.join("DO $r$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='"+n+"') THEN CREATE ROLE "+n+
        " NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; "
        "ELSIF EXISTS(SELECT FROM pg_roles WHERE rolname='"+n+"' AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) "
        "OR EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE r.rolname='"+n+"') "
        "THEN RAISE EXCEPTION 'Disabled isolated role required'; END IF; END $r$;" for n in identities if n!='g0_user')
    invoke(['exec','-i',container,'psql','-X','-q','-v','ON_ERROR_STOP=1','-U','g0_user','-d','postgres','-f','-'],role_sql)
    invoke(['exec',container,'createdb','-U','g0_user',database])
    binary(['exec','-i',container,'pg_restore','-U','g0_user','-d',database,'--single-transaction','--exit-on-error','--no-owner'],path,restore=True)


def scoped_login(container,database,operator=False):
    owned_pg(container);test_database(database)
    user,password='raa_wp4_portal_test_'+uuid4().hex[:12],secrets.token_hex(32);retain(password)
    signatures='retail.api_operator_reconcile_portal_v1(uuid,text,text)' if operator else ','.join(SIGNATURES)
    query(container,database,"BEGIN; CREATE ROLE "+user+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4 PASSWORD '"+password+"'; "
      "GRANT CONNECT ON DATABASE "+database+" TO "+user+"; GRANT USAGE ON SCHEMA retail TO "+user+"; "
      "ALTER ROLE "+user+" IN DATABASE "+database+" SET default_transaction_read_only=on; "
      "ALTER ROLE "+user+" IN DATABASE "+database+" SET statement_timeout='5s'; GRANT EXECUTE ON FUNCTION "+signatures+" TO "+user+"; COMMIT;")
    return {'host':container,'dbname':database,'user':user,'password':password}


def fingerprint(container,database):
    tables=query(container,database,"BEGIN READ ONLY; SELECT tablename FROM pg_tables WHERE schemaname='retail' ORDER BY tablename; COMMIT;").splitlines()
    result={}
    for name in tables:
        expect(re.fullmatch(r'[a-z][a-z0-9_]{0,80}',name) is not None,'fixed-retail-table-identity')
        result[name]=query(container,database,"BEGIN READ ONLY; SET LOCAL timezone='UTC'; SELECT count(*)||'|'||encode(sha256(convert_to(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text COLLATE \"C\")::text,'[]'),'UTF8')),'hex') FROM retail."+name+" t; COMMIT;")
    return result
