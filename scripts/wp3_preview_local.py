"""Save a credential-free private preview using GETs to one fixed loopback API."""
import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import re
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18081/api/v1/cases/"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(opener, token, path, media_type):
    with opener.open(Request(BASE + path, headers={"Authorization": "Bearer " + token}), timeout=15) as response:
        if response.status != 200 or response.headers.get_content_type() != media_type:
            raise ValueError("Unexpected preview response")
        body = response.read(524289)
        if len(body) > 524288:
            raise ValueError("Oversized preview response")
        return body


def save_preview(case_id):
    case_id = str(UUID(str(case_id)))
    token = (ROOT / ".local" / "wp2-api" / "token").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise ValueError("Local API token is unavailable")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    before = fetch(opener, token, case_id, "application/json")
    payload = fetch(opener, token, case_id + "/revisions/1", "application/json")
    page = fetch(opener, token, case_id + "/revisions/1/preview", "text/html")
    after = fetch(opener, token, case_id, "application/json")
    again = fetch(opener, token, case_id + "/revisions/1", "application/json")
    meta = json.loads(before)
    digest = hashlib.sha256(payload).hexdigest()
    if before != after or payload != again or meta.get("payload_sha256") != digest:
        raise ValueError("Stored identity or bytes changed")
    if meta.get("approved") is not False or meta.get("published") is not False or meta.get("revision") != 1:
        raise ValueError("Only unapproved revision 1 is supported")
    if (token.encode() in page or digest.encode() not in page or case_id.encode() not in page
            or escape(payload.decode("utf-8"), quote=True).encode() not in page):
        raise ValueError("Preview identity/secret check failed")
    output = ROOT / "reports" / "private" / f"{case_id}-revision-1-preview.html"
    if not output.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Private output escapes the project")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != page:
            raise ValueError("Existing private preview differs; not overwritten")
    else:
        # Runtime artifact generation, not source editing. Never overwrite evidence.
        with output.open("xb") as stream:
            stream.write(page)
    print("PASS|read-only-preview|same-case-and-bytes|no-token|unapproved|sha256=" + digest)
    print("Private HTML: " + str(output))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", type=UUID)
    args = parser.parse_args()
    try:
        save_preview(args.case_id)
    except Exception:
        # Never expose HTTP bodies, authorization, paths from exceptions or DSNs.
        raise SystemExit("Preview check failed; private diagnostic details suppressed") from None


if __name__ == "__main__":
    main()
