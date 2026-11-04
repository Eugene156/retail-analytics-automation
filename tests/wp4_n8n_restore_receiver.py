"""Private authenticated canary receiver; no retail, publication or external tools."""
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import hmac
import json

TOKEN=Path('/run/receiver/token').read_text().strip()
STATS=Path('/run/stats/requests.json')
counts={'requests':0,'authorized':0,'unauthorized':0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path=='/health':value,status={'ready':True},200
        elif self.path=='/credential-check':
            counts['requests']+=1
            allowed=hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+TOKEN)
            counts['authorized' if allowed else 'unauthorized']+=1
            STATS.write_text(json.dumps(counts))
            value,status=({'restored_credential':True},200) if allowed else ({'denied':True},401)
        else:value,status={'denied':True},404
        self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps(value).encode())
    def do_POST(self):self.send_response(405);self.end_headers()


if __name__=='__main__':
    try:
        STATS.write_text(json.dumps(counts));HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
    except Exception:raise SystemExit('FAIL|private-restore-receiver') from None
