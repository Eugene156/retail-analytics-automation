"""Private provisioning and real loopback HTTP checks; no human approval."""
import argparse
from contextlib import contextmanager
from hashlib import sha256
from http.client import HTTPConnection
import json
import os
import re
import secrets
import tempfile
import time
from urllib.parse import urlencode
from wp2_api_local import ROOT, SECRET_DIR, docker
from wp4_reviewer_local import credentials, CASE

DSN = SECRET_DIR / "portal-dsn"
KEY = SECRET_DIR / "portal-login-key"
PROBES = ROOT / ".local" / "wp4-reviewer" / "portal-test-secrets.json"
DSN_PATTERN = r"postgresql://raa_wp4_portal_api:([a-f0-9]{64})@raa-g0-postgres-1:5432/raa_wp2_validation"
ORIGIN = "http://127.0.0.1:18081"


def secret_values():
    values = []
    service = SECRET_DIR / "token"
    if service.exists():
        token = service.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise RuntimeError("Invalid service token")
        values.append(sha256(token.encode("ascii")).hexdigest())
    if DSN.exists() != KEY.exists():
        raise RuntimeError("Partial portal configuration")
    if DSN.exists():
        connection, key = DSN.read_text(encoding="utf-8").strip(), KEY.read_text(encoding="utf-8").strip()
        match = re.fullmatch(DSN_PATTERN, connection)
        if not match or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise RuntimeError("Invalid portal configuration")
        values.extend((connection, match.group(1), key))
    if PROBES.exists():
        saved = read_registry()
        if not isinstance(saved, list) or any(not re.fullmatch(r"[a-f0-9]{64}(?:\.[0-9]{10}\.[a-f0-9]{64})?", x) for x in saved):
            raise RuntimeError("Invalid private test registry")
        values.extend(saved)
    return values


def retain(value):
    retain_many((value,))


@contextmanager
def registry_lock():
    """Serialize local host writers; OS releases the lock on process exit."""
    PROBES.parent.mkdir(parents=True, exist_ok=True)
    with PROBES.with_suffix('.lock').open('a+b') as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b'0'); handle.flush()
        deadline = time.monotonic()+10
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Private registry busy') from None
                time.sleep(.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_registry(saved):
    # Atomic same-directory replace prevents readers seeing truncated JSON.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=PROBES.parent,
                                     prefix='.portal-probes-', suffix='.tmp', delete=False) as handle:
        json.dump(saved, handle); handle.flush(); os.fsync(handle.fileno())
        temporary = handle.name
    deadline = time.monotonic()+10
    while True:
        try:
            os.replace(temporary, PROBES)
            return
        except PermissionError:
            # Windows readers may briefly hold a handle without delete sharing.
            if time.monotonic() >= deadline:
                raise RuntimeError('Private registry replace denied; temporary retained') from None
            time.sleep(.02)


def retain_many(values):
    # Generated runtime probe secrets, not source edits. Preserve earlier values
    # so subsequent log checks cover prior runs and hashes too.
    with registry_lock():
        saved = json.loads(PROBES.read_text(encoding="utf-8")) if PROBES.exists() else []
        known = set(saved)
        for value in values:
            for item in (value, sha256(value.encode("ascii")).hexdigest()):
                if item not in known:
                    saved.append(item)
                    known.add(item)
        write_registry(saved)


def read_registry():
    # Windows replacement can briefly deny independent open/read handles.
    # All production consumers share the writer's OS lock as well.
    with registry_lock():
        return json.loads(PROBES.read_text(encoding='utf-8')) if PROBES.exists() else []


def recover_probe_registry():
    """Explicit local repair only; preserve the exact malformed bytes privately.

    Salvage complete supported credential/digest/challenge strings. This cannot
    certify missing/truncated historical entries or an entire secret audit.
    """
    with registry_lock():
        raw=PROBES.read_bytes()
        backup=PROBES.with_name('portal-test-secrets-corrupt-'+secrets.token_hex(6)+'.json')
        with backup.open('xb') as handle:handle.write(raw)
        pattern=r'(?<![a-f0-9])[a-f0-9]{64}(?:\.[0-9]{10}\.[a-f0-9]{64})?(?![a-f0-9])'
        saved=list(dict.fromkeys(re.findall(pattern,raw.decode('utf-8'))))
        if not saved:
            raise RuntimeError('No supported probe values; original/backup retained')
        write_registry(saved)
        return len(saved)


def bootstrap():
    credentials()  # Do not invent/replace the owner's mapping.
    guard = docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-qAt", "-U", "g0_user",
        "-d", "raa_wp2_validation", "-c", "SELECT EXISTS(SELECT 1 FROM retail.schema_migrations "
        "WHERE version=18 AND name='owner_portal_sessions') AND EXISTS(SELECT 1 FROM pg_roles "
        "WHERE rolname='raa_wp4_portal_api' AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolbypassrls);"])
    if guard != "t" or not SECRET_DIR.is_dir():
        raise RuntimeError("Migration 018 and existing owner configuration required")
    if DSN.exists()!=KEY.exists():
        raise RuntimeError("Partial configuration; not overwritten")
    if not DSN.exists():
        with DSN.open("x", encoding="utf-8") as stream:
            stream.write("postgresql://raa_wp4_portal_api:"+secrets.token_hex(32)+"@raa-g0-postgres-1:5432/raa_wp2_validation\n")
        with KEY.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_hex(32)+"\n")
    secret_values()
    password = re.fullmatch(DSN_PATTERN, DSN.read_text(encoding="utf-8").strip()).group(1)
    docker(["exec", "-i", "raa-g0-postgres-1", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
        "-U", "g0_user", "-d", "raa_wp2_validation", "-f", "-"],
        "BEGIN; ALTER ROLE raa_wp4_portal_api LOGIN PASSWORD '"+password+"'; COMMIT;")
    print("PASS|portal-bootstrap|separate-auth-state-role|owner-credential-preserved")


def http(path, method="GET", fields=None, headers=None, raw=None, extra=None):
    if not path.startswith(("/portal", "/review/", "/api/")) or "?" in path:
        raise RuntimeError("Fixed local path required")
    connection = HTTPConnection("127.0.0.1", 18081, timeout=15)
    body = raw if raw is not None else (urlencode(fields).encode() if fields is not None else None)
    try:
        connection.putrequest(method, path, skip_host=True)
        supplied = {"Host": "127.0.0.1:18081", **(headers or {})}
        if body is not None:
            supplied.setdefault("Content-Type", "application/x-www-form-urlencoded")
            supplied["Content-Length"] = str(len(body))
        for name, value in supplied.items():
            connection.putheader(name, value)
        for name, value in extra or []:
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        payload = response.read(524289)
        if len(payload)>524288 or credentials()["token"].encode() in payload:
            raise RuntimeError("Response privacy/size guard failed")
        return response.status, payload, response.getheaders()
    finally:
        connection.close()


def cookie(headers, name):
    matches = [v.split(";",1)[0].split("=",1)[1] for k,v in headers
               if k.lower()=="set-cookie" and v.startswith(name+"=") and "Max-Age=0" not in v]
    if len(matches)!=1:
        raise RuntimeError("Expected one private cookie")
    value = matches[0]
    retain(value)
    return value


def nonce(body):
    matches = re.findall(rb'name="csrf" value="([a-f0-9]{64})"', body)
    if not matches or len(set(matches))!=1:
        raise RuntimeError("Expected one form challenge")
    value = matches[0].decode()
    retain(value)
    return value


def require(condition):
    if not condition:
        raise RuntimeError("Portal check failed; response details suppressed")


def snapshot():
    return docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-qAt", "-U", "g0_user", "-d", "raa_wp2_validation",
        "-c", "SELECT (SELECT count(*) FROM retail.report_cases), (SELECT count(*) FROM retail.report_revisions), "
        "(SELECT count(*) FROM retail.approval_requests_v2),(SELECT count(*) FROM retail.approval_request_events_v2), "
        "(SELECT count(*) FROM retail.review_decisions_v1),(SELECT count(*) FROM retail.review_decision_events_v1), "
        "(SELECT count(*) FROM retail.publication_outbox_v1), "
        "encode(sha256(convert_to(retail.api_get_case_v1('"+CASE+"') || "
        "retail.api_get_revision_v1('"+CASE+"',1),'UTF8')),'hex');"])


def check():
    before = snapshot()
    owner = credentials()
    status, body, headers = http("/portal/login")
    response_headers={k.lower():v for k,v in headers}
    require(status==200 and response_headers.get("cache-control")=="no-store"
            and response_headers.get("referrer-policy")=="same-origin")
    challenge, csrf = cookie(headers,"raa_portal_login"), nonce(body)
    form = {"owner_token": owner["token"], "csrf": csrf}
    base = {"Cookie": "raa_portal_login="+challenge, "Origin": ORIGIN}
    require(http("/portal")[0]==303)
    require(http("/portal/login", headers={"Host":"localhost:18081"})[0]==400)
    require(http("/portal/login", extra=[("Host","127.0.0.1:18081")])[0]==400)
    for origin in (None, "null", "http://evil.invalid", "http://127.0.0.1:18082"):
        h = {"Cookie":base["Cookie"]}
        if origin is not None:
            h["Origin"]=origin
        require(http("/portal/login","POST",form,h)[0]==403)
    require(http("/portal/login","POST",form,base,extra=[("Origin",ORIGIN)])[0]==403)
    require(http("/portal/login","POST",form,base,extra=[("Cookie",base["Cookie"])])[0]==400)
    bad = {**form,"csrf":"0"*64}
    require(http("/portal/login","POST",bad,base)[0]==403)
    for token in ("wrong", "0"*64, (SECRET_DIR/"token").read_text(encoding="utf-8").strip()):
        require(http("/portal/login","POST",{**form,"owner_token":token},base)[0]==401)
    require(http("/portal/login","POST",None,base,raw=b"x"*2049)[0]==413)
    require(http("/portal/login","POST",form,{**base,"Content-Type":"application/json"})[0]==415)
    status, body, headers = http("/portal/login","POST",form,base)
    require(status==303)
    first = cookie(headers,"raa_portal_session")
    cookie_header = next(v for k,v in headers if k.lower()=="set-cookie" and v.startswith("raa_portal_session="))
    require("HttpOnly" in cookie_header and "SameSite=strict" in cookie_header and "Path=/portal" in cookie_header
            and "Max-Age=3600" in cookie_header and "Secure" not in cookie_header)
    status, body, headers = http("/portal", headers={"Cookie":"raa_portal_session="+first})
    require(status==200 and first.encode() not in body)
    require({k.lower():v for k,v in headers}.get("referrer-policy")=="same-origin")
    nonce(body)
    require(http("/review/v1/identity",headers={"Cookie":"raa_portal_session="+first})[0]==401)
    require(http("/api/v1/cases/"+CASE,headers={"Cookie":"raa_portal_session="+first})[0]==401)
    # A second login rotates only this test session, not the owner's credential.
    status, body, headers = http("/portal/login")
    challenge, csrf = cookie(headers,"raa_portal_login"), nonce(body)
    status, body, headers = http("/portal/login","POST",{"owner_token":owner["token"],"csrf":csrf},
        {"Cookie":"raa_portal_login="+challenge+"; raa_portal_session="+first,"Origin":ORIGIN})
    require(status==303)
    second = cookie(headers,"raa_portal_session")
    require(first!=second and http("/portal",headers={"Cookie":"raa_portal_session="+first})[0]==303)
    session_headers = {"Cookie":"raa_portal_session="+second}
    status, body, headers = http("/portal",headers=session_headers)
    require(status==200)
    logout_csrf = nonce(body)
    links = re.findall(rb'href="(/portal/cases/[a-f0-9-]+/requests/[a-f0-9-]+)"',body)
    require(bool(links))
    status, body, headers = http(links[0].decode(),headers=session_headers)
    require(status==200 and b"Unpublished" in body and second.encode() not in body)
    nonce(body)
    # Always invalid report hash: this diagnostic can never approve real M02.
    hidden=dict((name.decode(),value.decode()) for name,value in re.findall(
        rb'<input type="hidden" name="([^"]+)" value="([^"]+)">',body))
    require(set(hidden)=={'csrf','revision','report_sha256','proposal_sha256','decision_key'})
    require({k.lower():v for k,v in headers}.get('x-decision-enabled')=='true')
    invalid={**hidden,'report_sha256':'0'*64,'choice':'approve','confirm':'yes'}
    require(http(links[0].decode()+'/decision','POST',{**invalid,'csrf':'0'*64},
        {**session_headers,'Origin':ORIGIN})[0]==403)
    require(http(links[0].decode()+'/decision','POST',invalid,{**session_headers,'Origin':ORIGIN})[0]==409)
    require(http(links[0].decode()+'/decision','POST',{**invalid,'confirm':'no'},
        {**session_headers,'Origin':ORIGIN})[0]==422)
    require(http("/portal/cases/"+CASE+"/revisions/1/preview",headers=session_headers)[0]==200)
    require(http("/portal/logout","POST",{"csrf":"0"*64},{**session_headers,"Origin":ORIGIN})[0]==403)
    require(http("/portal/logout",headers=session_headers)[0]==405)
    require(http(links[0].decode(),"POST",{"csrf":logout_csrf},{**session_headers,"Origin":ORIGIN})[0]==405)
    require(http("/portal/logout","POST",{"csrf":logout_csrf},{**session_headers,"Origin":ORIGIN})[0]==303)
    require(http("/portal",headers=session_headers)[0]==303)
    require(http("/portal/logout","POST",{"csrf":logout_csrf},{**session_headers,"Origin":ORIGIN})[0]==401)
    require(snapshot()==before)
    print("PASS|portal-real-http|login-origin-csrf-body-host-cookie|rotation-logout|decision-form-invalid-binding-denials|auth-separation|business-state-unchanged")


def database_check():
    owner=credentials()
    private=json.dumps({'digest':sha256(owner['token'].encode()).hexdigest(),'reviewer_id':owner['reviewer_id'],
        'service_digest':sha256((SECRET_DIR/'token').read_text(encoding='utf-8').strip().encode()).hexdigest()})
    docker(['exec','-i','-e','RAA_RUN_PORTAL_DB_TESTS=1','raa-wp2-api','python','-m','unittest',
        'discover','-s','tests','-p','test_wp4_portal_database.py','-v'],private)
    print('PASS|three-actual-portal-login-tests|scoped-rights|transactional-login-logout-rollback|service-denial')


def check_restart():
    import time
    before=snapshot()
    status,body,headers=http('/portal/login')
    require(status==200)
    challenge,csrf=cookie(headers,'raa_portal_login'),nonce(body)
    status,body,headers=http('/portal/login','POST',{'owner_token':credentials()['token'],'csrf':csrf},
        {'Cookie':'raa_portal_login='+challenge,'Origin':ORIGIN})
    require(status==303)
    raw=cookie(headers,'raa_portal_session')
    session_headers={'Cookie':'raa_portal_session='+raw}
    session_digest=sha256(raw.encode()).hexdigest()
    def times():
        return docker(['exec','-i','raa-g0-postgres-1','psql','-X','-qAt','-v','ON_ERROR_STOP=1',
            '-U','g0_user','-d','raa_wp2_validation','-f','-'],
            "SELECT created_at,expires_at FROM retail.owner_portal_sessions WHERE session_sha256='"+session_digest+"';")
    try:
        deadline=times()
        require(bool(deadline))
        docker(['restart','raa-wp2-api'])
        for _ in range(20):
            try:
                status,body,headers=http('/portal',headers=session_headers)
                if status==200:
                    break
            except OSError:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError('API did not become ready')
        require(times()==deadline)
        require(snapshot()==before)
        logout_csrf=nonce(body)
        require(http('/portal/logout','POST',{'csrf':logout_csrf},{**session_headers,'Origin':ORIGIN})[0]==303)
    finally:
        # Best-effort close this test session only; never delete history.
        status,body,headers=http('/portal',headers=session_headers)
        if status==200:
            http('/portal/logout','POST',{'csrf':nonce(body)},{**session_headers,'Origin':ORIGIN})
    print('PASS|portal-session-survived-api-restart|absolute-deadline-unchanged|test-session-logged-out|business-state-unchanged')


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["bootstrap","check","database-check","check-restart"])
    args = parser.parse_args()
    try:
        {"bootstrap":bootstrap,"check":check,"database-check":database_check,"check-restart":check_restart}[args.action]()
    except Exception as error:
        import traceback
        line = traceback.extract_tb(error.__traceback__)[-1].lineno
        raise SystemExit(f"FAIL|portal-local-operation|{type(error).__name__}|line-{line}|details-suppressed-to-protect-secrets") from None
