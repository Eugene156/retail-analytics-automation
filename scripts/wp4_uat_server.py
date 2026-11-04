"""Explicit isolated-UAT entry point; no admin/operator/real owner configuration."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if __name__=='__main__':
    try:
        import uvicorn
        from api.portal_uat import build_app
        if sys.argv[1:] not in (['owner'],['worker']):raise ValueError()
        mode=sys.argv[1]
        config=json.loads(Path('/run/uat/config.json').read_text(encoding='utf-8'))
        app=build_app(config,mode)
        # Bootstrap admission completes BEFORE uvicorn binds any socket.
        uvicorn.run(app,host='0.0.0.0',port=8000,access_log=False,log_level='error',
                    proxy_headers=False,server_header=False)
    except Exception:raise SystemExit('FAIL|isolated-uat-server|admission-or-runtime-denied|details-suppressed') from None
