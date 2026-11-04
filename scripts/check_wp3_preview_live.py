"""Actual loopback HTTP guards plus unchanged stored-byte/private-preview checks."""
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from wp3_preview_local import BASE, ROOT, NoRedirect, save_preview

CASE_ID = "61b10574-c842-4dae-8e8b-647f0d51ba55"


def main():
    token = (ROOT / ".local" / "wp2-api" / "token").read_text(encoding="utf-8").strip()
    opener = build_opener(ProxyHandler({}), NoRedirect())
    path = CASE_ID + "/revisions/1/preview"
    scenarios = [("GET", path, None, 401), ("GET", path, "wrong", 401),
                 ("POST", path, token, 405), ("GET", path.replace("/1/", "/2/"), token, 404),
                 ("GET", path.replace("/1/", "/" + "9" * 60 + "/"), token, 404),
                 ("GET", "00000000-0000-0000-0000-000000000000/revisions/1/preview", token, 404)]
    for method, suffix, auth, expected in scenarios:
        headers = {} if auth is None else {"Authorization": "Bearer " + auth}
        try:
            with opener.open(Request(BASE + suffix, method=method, headers=headers), timeout=15) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
            error.close()
        if status != expected:
            raise ValueError("Preview HTTP guard failed")
    with opener.open(Request(BASE + path, headers={"Authorization": "Bearer " + token}), timeout=15) as response:
        if (response.headers.get("Cache-Control") != "no-store"
                or response.headers.get("X-Content-Type-Options") != "nosniff"
                or response.headers.get("X-Report-Status") != "unapproved-draft"
                or "script-src 'none'" not in response.headers.get("Content-Security-Policy", "")):
            raise ValueError("Preview HTTP protections missing")
    save_preview(CASE_ID)
    save_preview(CASE_ID)  # Deterministic same-file replay, not overwrite.
    print("PASS|actual-http-preview|missing-wrong-auth|post-405|missing-unsupported-404|security-headers|repeatable")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Live preview check failed; private diagnostics suppressed") from None
