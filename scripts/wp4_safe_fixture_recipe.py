"""Fixed-path offline recipe export. No Docker, SQL execution or secret reads."""
from hashlib import file_digest,sha256
import gzip
import io
import json
from pathlib import Path

import wp4_safe_fixture_contract as i1
import wp4_safe_fixture_planner as p

ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/'.local/wp4-safe-public-checkpoints'/i1.PUBLIC_CHECKPOINT
OUTPUT=ROOT/'.local/wp4-safe-fixture-I2/recipe-output'
KEY='42b4d3b2-98d8-4d0f-a7fd-25c3c66466ad'
ARTIFACTS=('source-workbook.xlsx','public-rows.jsonl.gz','baseline.json','service-fixtures.json','schema-plan.json','legacy-report-candidate.json')


def no_links(path):
    p.require(all(not part.is_symlink() and not part.is_junction() for part in (path,*path.parents)))


def digest(path):
    with path.open('rb') as stream:return file_digest(stream,'sha256').hexdigest()


def read_fixed(path):
    no_links(path);p.require(path.is_file());return path.read_bytes()


def load_inputs():
    migrations=[]
    for number in range(1,30):
        paths=list((ROOT/'db/migrations').glob(f'{number:03d}_*.sql'));p.require(len(paths)==1)
        path=paths[0];migrations.append((path.name,read_fixed(path).replace(b'\r\n',b'\n')))
    return p.Inputs(tuple(migrations),read_fixed(ROOT/'db/import_finalize.sql').replace(b'\r\n',b'\n')).checked()


def validate_public():
    raw=read_fixed(PUBLIC/'manifest.json');p.require(sha256(raw).hexdigest()==i1.SOURCE['manifest_sha256'])
    record=json.loads(raw);p.require(set(record['artifacts'])==set(ARTIFACTS))
    p.require({path.name for path in PUBLIC.iterdir()}==set(ARTIFACTS)|{'manifest.json'})
    for name,entry in record['artifacts'].items():
        no_links(PUBLIC/name)
        p.require((PUBLIC/name).stat().st_size==entry['bytes'] and digest(PUBLIC/name)==entry['sha256'])
    return record


def public_rows():
    # Decompress exactly the immutable compressed bytes whose hash was checked.
    record=validate_public();path=PUBLIC/'public-rows.jsonl.gz'
    entry=record['artifacts']['public-rows.jsonl.gz'];no_links(path)
    with path.open('rb') as stream:data=stream.read(entry['bytes']+1)
    p.require(len(data)==entry['bytes'] and sha256(data).hexdigest()==entry['sha256'])
    with gzip.GzipFile(fileobj=io.BytesIO(data),mode='rb') as stream:
        while True:
            line=stream.readline(65537)
            if not line:break
            p.require(len(line)<=65536 and line.endswith(b'\n'))
            yield json.loads(line)


def write(path,chunks):
    no_links(path);hasher=sha256();size=0
    with path.open('xb') as stream:
        for chunk in chunks:
            p.require(type(chunk) is bytes);stream.write(chunk);hasher.update(chunk);size+=len(chunk)
    return dict(bytes=size,sha256=hasher.hexdigest())


def seal_inventory(artifacts):
    expected_dirs={'source-build','reference-build'};seen_files=set();seen_dirs=set()
    for path in OUTPUT.rglob('*'):
        no_links(path);name=path.relative_to(OUTPUT).as_posix()
        if path.is_dir():seen_dirs.add(name)
        else:
            p.require(path.is_file() and name in artifacts);seen_files.add(name)
            entry=artifacts[name]
            p.require(path.stat().st_size==entry['bytes'] and digest(path)==entry['sha256'])
    p.require(seen_files==set(artifacts) and seen_dirs==expected_dirs)


def export():
    """Only export static non-secret recipes. Manifest last; never overwrite."""
    inputs=load_inputs();validate_public();no_links(OUTPUT)
    p.require(not OUTPUT.exists());OUTPUT.mkdir()
    sources={};artifacts={}
    def emit(path,chunks):
        name=path.relative_to(OUTPUT).as_posix();p.require(name not in artifacts)
        artifacts[name]=write(path,chunks)
    for purpose in ('source-build','reference-build'):
        context=i1.ScopedContext.from_contract(i1.canonical(i1.proposal(KEY)),purpose)
        directory=OUTPUT/purpose;directory.mkdir()
        raw=p.CapturePlanner(context,inputs).document();p.validate_recipe(raw,context,inputs)
        emit(directory/'recipe.json',(raw,));sources[purpose]=sha256(raw).hexdigest()
        for name,body in p.migration_batches(context,inputs):emit(directory/name,(body,))
        emit(directory/'report-alias.sql',(p.report_alias_sql(context,inputs),))
    context=i1.ScopedContext.from_contract(i1.canonical(i1.proposal(KEY)),'source-build')
    emit(OUTPUT/'public-import.sql',p.import_chunks(context,inputs,public_rows(),p.SHEETS))
    # Reference may replay the same import with the same provenance ID in its
    # distinct cluster. Secret seeding/ownership/rename/capture are native steps,
    # not falsely completed artifacts or runnable lifecycle scripts.
    validate_public()
    p.require(inputs==load_inputs())
    seal_inventory(artifacts)
    manifest=dict(version=p.VERSION,status='offline-generated-not-executed',checkpoint_id=KEY,
        recipes=sources,artifacts=artifacts,native_evidence_acquired=False,materialization_allowed=False,
        application_writers_admitted=False,external_dispatch_allowed=False,blocked_gates=list(i1.GATES))
    write(OUTPUT/'manifest.json',(i1.canonical(manifest),))
    print('PASS|I2-offline-export|public-physical-rows|native-not-run',flush=True)
    return 2


if __name__=='__main__':
    try:raise SystemExit(export())
    except Exception:
        print('FAIL|I2-offline-export|details-suppressed');raise SystemExit(1)
