"""Private n8n snapshot mechanics. No live workflow execution or main restore."""
from hashlib import sha256
import json
from pathlib import Path
import re
import tarfile
from wp3_n8n_local import ROOT,PG,invoke,expect
from wp4_recovery_storage import query,binary,test_database,owned_pg


def private(path):
    expect(path.resolve().is_relative_to((ROOT/'.local/wp4-recovery').resolve()),'n8n-private-snapshot-path')
    return path


def fingerprint(container,database,source=False):
    if source:expect(container==PG and database=='n8n','exact-source-metadata')
    else:owned_pg(container);test_database(database)
    def sql(value):return invoke(['exec','-i',container,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','g0_user','-d',database,'-f','-'],value).stdout.strip()
    tables=sql("BEGIN READ ONLY; SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename; COMMIT;").splitlines()
    expect(tables and all(re.fullmatch(r'[a-z][a-z0-9_]{0,80}',n) for n in tables),'bounded-metadata-tables')
    statements=[]
    for n in tables:
        statements.append("SELECT '"+n+"',count(*),encode(sha256(convert_to(coalesce(string_agg(d,' ' ORDER BY d COLLATE \"C\"),''),'UTF8')),'hex') FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') d FROM public.\""+n+"\" t) r")
    result=sql("BEGIN READ ONLY; SET LOCAL timezone='UTC'; "+';'.join(statements)+"; SELECT 'sequence',sequencename,coalesce(last_value::text,'null') FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename; COMMIT;")
    return {'tables':len(tables),'rows_sha256':sha256(result.encode()).hexdigest()}


def backup(path):
    private(path)
    binary(['exec',PG,'pg_dump','-U','g0_user','-d','n8n','--format=custom','--no-owner','--schema=public'],path)
    data=path.read_bytes();expect(data[:5]==b'PGDMP','n8n-custom-backup-format')
    return {'bytes':len(data),'sha256':sha256(data).hexdigest()}


def restore(container,database,path):
    owned_pg(container);test_database(database);private(path)
    invoke(['exec',container,'createdb','-U','g0_user',database])
    # pg_dump includes CREATE SCHEMA public. Only this newly created empty test
    # database may shed its default namespace; no CASCADE or existing DB reuse.
    expect(query(container,database,"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public';")=='0','new-public-schema-empty')
    query(container,database,'DROP SCHEMA public;')
    binary(['exec','-i',container,'pg_restore','-U','g0_user','-d',database,'--single-transaction','--exit-on-error','--no-owner'],path,restore=True)


def home_backup(path):
    private(path);root=(ROOT/'volumes/g0/n8n').resolve()
    expect(root.is_dir() and (root/'config').is_file(),'saved-n8n-home-present')
    manifest={}
    with tarfile.open(path,'x') as archive:
        for item in sorted(root.rglob('*')):
            expect(not item.is_symlink() and not item.is_junction() and item.resolve().is_relative_to(root),'no-home-link-escape')
            name=item.relative_to(root).as_posix()
            expect(not name.startswith('nodes/node_modules/'),'no-unreviewed-custom-node-packages')
            if item.is_file():
                manifest[name]=sha256(item.read_bytes()).hexdigest()
                archive.add(item,arcname=name,recursive=False)
    return manifest


def safe_archive(path):
    private(path)
    with tarfile.open(path) as archive:
        for item in archive.getmembers():
            parts=Path(item.name).parts
            expect(item.isfile() and not item.name.startswith('/') and not Path(item.name).is_absolute() and '\\' not in item.name
                and ':' not in item.name and '..' not in parts,'fixed-home-archive-members')


def settings(saved,cluster,database,password,workflow):
    test_database(database)
    expect(re.fullmatch(r'raa-wp4-recovery-postgres-[a-f0-9]{12}',cluster) is not None,'fixed-restored-PG')
    expect(re.fullmatch(r'raa-wp4-n8n-canary-[a-f0-9]{12}',workflow) is not None,'fixed-restore-canary')
    expect(saved['N8N_RUNNERS_ENABLED']=='true' and saved['N8N_RUNNERS_MODE']=='external','saved-external-runner-settings')
    return {'workflow':workflow,'env':dict(saved,DB_POSTGRESDB_HOST=cluster,DB_POSTGRESDB_DATABASE=database,
        DB_POSTGRESDB_USER='g0_user',DB_POSTGRESDB_PASSWORD=password)}
