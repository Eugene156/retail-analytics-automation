"""P4-only dependency operations. Docker mutations require owner approval."""
import argparse
from hashlib import file_digest
import json
from pathlib import Path
import secrets
import shutil
import subprocess

import p1_demo as p1

PRIVATE=p1.ROOT/'.local/p4-demo'
CACHE=p1.ROOT/'models/p4-embedding'
IMAGE='pgvector/pgvector:0.8.7-pg17-bookworm'
HELPER='raa-p4-demo-embedding-helper'
PG='raa-p4-demo-rag-postgres-1'
OLLAMA='sha256:0c0a83210471fb50226bcdc2d6611d20ab13ae87e024cc304c94a6a5765c5e65'


def absent(kind,name):
    args=['container','ls','-a','--filter','name=^/'+name+'$','--format','{{.Names}}'] if kind=='container' else ['volume','ls','--filter','name=^'+name+'$','--format','{{.Name}}']
    assert not p1.docker(args).strip(),'Existing P4 resource; preserve state'


def prepare():
    assert not PRIVATE.exists() and not CACHE.exists(),'Existing P4 files preserved'
    PRIVATE.mkdir(parents=True);CACHE.mkdir(parents=True)
    (PRIVATE/'postgres-password').write_text(secrets.token_hex(32)+'\n')
    # Preserve existing workspace ACL; no permission expansion or ACL mutation.
    print('PREPARED|fresh-ignored-P4-password|isolated-cache|no-Docker-mutation')


def digest_file(path):
    with path.open('rb') as stream: return file_digest(stream,'sha256').hexdigest()


def dependencies():
    p1.guard();absent('container',HELPER);absent('container',PG);absent('volume','raa-p4-demo_rag_data')
    assert (PRIVATE/'postgres-password').is_file() and CACHE.is_dir()
    assert subprocess.run(['git','check-ignore',str(PRIVATE/'postgres-password')],capture_output=True).returncode==0
    network=json.loads(p1.docker(['network','inspect','raa-p1-demo_default']))[0]
    assert network['Internal'] and network['Labels']['com.docker.compose.project']=='raa-p1-demo'
    p1.docker(['pull',IMAGE],timeout=900)
    print('DOWNLOADED|approved-pgvector-image',flush=True)
    command='ollama serve >/tmp/serve.log 2>&1 & pid=$!; trap "kill $pid 2>/dev/null || true" EXIT; i=0; until ollama list >/dev/null 2>&1; do i=$((i+1)); [ "$i" -lt 30 ] || exit 1; sleep 1; done; ollama pull all-minilm:22m'
    p1.docker(['run','--name',HELPER,'--label','com.docker.compose.project=raa-p4-demo',
               '--pull','never','--network','bridge','--memory','512m','--cpus','2','--pids-limit','128',
               '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
               '--tmpfs','/tmp:rw,nosuid,size=32m','--tmpfs','/root/.ollama:rw,nosuid,size=16m',
               '--mount','type=bind,source='+str(CACHE)+',target=/models',
               '-e','OLLAMA_MODELS=/models','-e','OLLAMA_NO_CLOUD=true',
               '--entrypoint','sh',OLLAMA,'-c',command],timeout=900)
    state=json.loads(p1.docker(['inspect',HELPER,'--format','{{json .State}}']))
    assert state['ExitCode']==0 and not state['OOMKilled'] and not state['Running']
    assert (CACHE/'manifests/registry.ollama.ai/library/all-minilm/22m').is_file()
    old=json.loads(p1.docker(['inspect','raa-p2-demo-ollama-1','--format','{{json .Mounts}}']))
    target=Path(next(m['Source'] for m in old if m['Destination']=='/models'))
    assert target.resolve()==(p1.ROOT/'models/ollama/models').resolve()
    # Add only new embedding files. Existing model files are never overwritten.
    before={str(f.relative_to(target)):digest_file(f) for f in target.rglob('*') if f.is_file()}
    files=[f for f in CACHE.rglob('*') if f.is_file()]
    for f in files:
        rel=f.relative_to(CACHE)
        assert str(rel).replace('\\','/').startswith(('blobs/','manifests/registry.ollama.ai/library/all-minilm/'))
        assert not f.is_symlink()
        dest=target/rel
        if dest.exists(): assert digest_file(dest)==digest_file(f)
    for f in files:
        dest=target/f.relative_to(CACHE)
        if not dest.exists(): dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
    assert all(digest_file(target/rel)==digest for rel,digest in before.items())
    digest=p1.docker(['image','inspect',IMAGE,'--format','{{index .RepoDigests 0}}']).strip()
    (PRIVATE/'dependencies.json').write_text(json.dumps({'pgvector_image':digest,'embedding_model':'all-minilm:22m','existing_model_files_unchanged':True,'helper_retained':True},indent=2)+'\n')
    print('DOWNLOADED|all-minilm22m|old-model-hashes-unchanged|helper-retained',flush=True)
    start_postgres()


def start_postgres():
    p1.guard();absent('container',PG);absent('volume','raa-p4-demo_rag_data')
    assert (PRIVATE/'dependencies.json').is_file()
    # Compose declares one P4 service, fresh volume/secret and existing internal network.
    config=json.loads(p1.docker(['compose','-f',str(p1.ROOT/'demo/p4.compose.yaml'),'config','--format','json']))
    assert config['name']=='raa-p4-demo' and set(config['services'])=={'rag-postgres'}
    service=config['services']['rag-postgres']
    assert int(service['mem_limit'])==536870912 and not service.get('ports')
    assert config['volumes']['rag_data']['name']=='raa-p4-demo_rag_data'
    p1.docker(['compose','-f',str(p1.ROOT/'demo/p4.compose.yaml'),'up','-d','--no-deps','--pull','never','rag-postgres'])
    print('STARTED|P4-only-PostgreSQL|512MiB|no-published-ports')


def guard_p4():
    p1.guard()
    value=json.loads(p1.docker(['inspect',PG]))[0]
    assert value['Config']['Labels']['com.docker.compose.project']=='raa-p4-demo'
    assert value['HostConfig']['Memory']==536870912 and not value['HostConfig'].get('PortBindings')
    volumes=[m['Name'] for m in value['Mounts'] if m['Type']=='volume']
    assert volumes==['raa-p4-demo_rag_data'] and not value['State']['OOMKilled']


def sql_p4(statement):
    return p1.docker(['exec','-i',PG,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','raa_p4_owner','-d','raa_p4_rag','-f','-'],statement).strip()


def prepare_credentials():
    for name in ('ingest-password','read-password'):
        path=PRIVATE/name
        if not path.exists(): path.write_text(secrets.token_hex(32)+'\n')
        assert subprocess.run(['git','check-ignore',str(path)],capture_output=True).returncode==0
    print('PREPARED|two-fresh-ignored-role-passwords|no-Docker-mutation')


def deploy():
    """Requires NEW owner approval: P4 DDL and 2 credentials/3 n8n imports."""
    import p4_workflows as w
    guard_p4()
    assert sql_p4("SELECT current_database()||'|'||(SELECT count(*) FROM pg_namespace WHERE nspname='p4')||'|'||(SELECT count(*) FROM pg_roles WHERE rolname IN ('raa_p4_ingest','raa_p4_read')); ")=='raa_p4_rag|0|0'
    ids="'"+"','".join((w.INDEX,w.PARENT,w.CORE))+"'"
    assert p1.sql('SELECT count(*) FROM workflow_entity WHERE id IN ('+ids+');','n8n')=='0'
    assert p1.sql("SELECT count(*) FROM credentials_entity WHERE id IN ('p4-rag-ingest','p4-rag-read');",'n8n')=='0'
    assert p1.docker(['inspect','raa-p1-demo-n8n-1','--format','{{index .Config.Labels "com.docker.compose.project"}}']).strip()=='raa-p1-demo'
    prepared=w.workflows()
    for filename,workflow in zip(('p4_rag_index.json','p4_rag_demo.json','p4_rag_core.json'),prepared):
        assert json.loads((p1.ROOT/'workflows'/filename).read_text())==workflow
    credentials=[];roles=[]
    for mode in ('ingest','read'):
        password=(PRIVATE/(mode+'-password')).read_text().strip()
        assert len(password)==64 and all(c in '0123456789abcdef' for c in password)
        roles.append("CREATE ROLE raa_p4_"+mode+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '"+password+"';")
        credentials.append({'id':'p4-rag-'+mode,'name':'P4 RAG index only' if mode=='ingest' else 'P4 RAG read only','type':'postgres',
                            'data':{'host':PG,'database':'raa_p4_rag','user':'raa_p4_'+mode,'password':password,'port':5432}})
    sql_p4('BEGIN;\n'+'\n'.join(roles)+'\n'+(p1.ROOT/'demo/p4_schema.sql').read_text()+'\nCOMMIT;')
    p1.docker(['exec','-i','raa-p1-demo-n8n-1','n8n','import:credentials','--input=/dev/stdin'],json.dumps(credentials))
    for workflow in prepared:
        p1.docker(['exec','-i','raa-p1-demo-n8n-1','n8n','import:workflow','--input=/dev/stdin'],json.dumps(workflow))
    print('DEPLOYED|P4-only-schema-vector-role-grants|two-new-credentials|three-new-workflows|P1-P3-preserved')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('prepare','dependencies','start_postgres','prepare_credentials','deploy'))
    try: globals()[parser.parse_args().operation]()
    except Exception: raise SystemExit('BLOCKED|P4-operation|details-suppressed|preserve-state') from None
