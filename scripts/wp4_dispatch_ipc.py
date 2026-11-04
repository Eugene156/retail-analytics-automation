"""Test-only stdlib Docker pipe transport. No DB ports or host dependencies."""
import json
import queue
import subprocess
import threading

from api.publication_dispatch import DispatchUncertain

SQL_TO_OP={
    'SELECT current_database()':'database',
    'SELECT retail.api_publication_state_v1(%s)':'state',
    'SELECT retail.api_claim_publication_v1(%s,%s,%s)':'claim',
    'SELECT retail.api_authorize_publication_v1(%s,%s)':'authorize',
    'SELECT retail.api_observe_publication_v1(%s,%s,%s,%s,%s)':'observe',
}


class PrivatePipe:
    def __init__(self,config,kind):
        self._queue=queue.Queue()
        self._process=subprocess.Popen(['docker','exec','-i','raa-wp2-api','python','-u','-c',
            "import sys,runpy; sys.path.insert(0,'/app/tests'); runpy.run_path('/app/tests/wp4_dispatch_ipc_server.py',run_name='__main__')"],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',bufsize=1)
        def receive():
            try:
                while True:
                    line=self._process.stdout.readline(1048577)
                    self._queue.put(line)
                    if not line: break
            except Exception: self._queue.put('')
        self._thread=threading.Thread(target=receive,daemon=True); self._thread.start()
        try:
            self._send(dict(config,kind=kind))
            self.initial=self._receive()
        except BaseException:
            self.close(); raise

    def _send(self,value):
        self._process.stdin.write(json.dumps(value)+'\n'); self._process.stdin.flush()

    def _receive(self):
        try:
            line=self._queue.get(timeout=12)
            if not line or len(line)>1048576: raise ValueError()
            value=json.loads(line)
            if value.get('ok') is not True: raise ValueError()
            return value['value']
        except Exception:
            raise DispatchUncertain('Private IPC outcome requires reconciliation') from None

    def call(self,op,args=None):
        try:
            value={'op':op}
            if args is not None: value['args']=list(args)
            self._send(value)
            return self._receive()
        except Exception:
            raise DispatchUncertain('Private IPC outcome requires reconciliation') from None

    def close(self):
        # Closing stdin yields EOF in the container: rollback/finally closes SQL.
        # Only this labeled subprocess is waited/killed, never a container/volume.
        try: self._process.stdin.close()
        except Exception: pass
        try: self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill(); self._process.wait(timeout=5)
        try: self._process.stdout.close()
        except Exception: pass


class _One:
    def __init__(self,value): self._value=value
    def fetchone(self): return (self._value,)


class PipeConnection:
    def __init__(self,config):
        # Worker subprocess never receives fixture admin credentials.
        self._pipe=PrivatePipe({'database':config['database'],'worker':config['worker']},'worker')
        self.autocommit=self._pipe.initial['autocommit']
        self._read_only=True

    def execute(self,sql,args=()):
        if sql not in SQL_TO_OP: raise ValueError('Only fixed dispatch SQL operations allowed')
        return _One(self._pipe.call(SQL_TO_OP[sql],args))

    def rollback(self): self._pipe.call('rollback')
    def commit(self): self._pipe.call('commit')
    def close(self): self._pipe.close()
    @property
    def read_only(self): return self._read_only
    @read_only.setter
    def read_only(self,value):
        if value is not False: raise ValueError('Fixed transaction mode required')
        self._pipe.call('write'); self._read_only=False
