"""Mock transport/protocol checks, not native filesystem or DB evidence."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import wp4_dispatch_ipc as transport
from api.publication_dispatch import DispatchUncertain

DB='raa_wp4_dispatch_test_0123456789ab'
CONFIG={'database':DB,'worker':{'host':'raa-g0-postgres-1','dbname':DB,
    'user':'raa_wp4_dispatch_test_abcdef012345','password':'synthetic-private-marker'},
    'admin':{'password':'never-forward-admin'}}


class IpcContracts(unittest.TestCase):
    def server(self):
        spec=importlib.util.spec_from_file_location('isolated_ipc_test',ROOT/'tests/wp4_dispatch_ipc_server.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'psycopg':Mock()}): spec.loader.exec_module(module)
        return module

    def test_worker_config_never_forwards_admin_or_puts_credentials_in_argv(self):
        pipe=Mock(); pipe.initial={'autocommit':False}
        with patch.object(transport,'PrivatePipe',return_value=pipe) as factory:
            conn=transport.PipeConnection(CONFIG)
        sent=factory.call_args.args[0]
        self.assertEqual(set(sent),{'database','worker'}); self.assertNotIn('admin',sent)
        self.assertFalse(conn.autocommit)

    def test_only_fixed_sql_maps_to_private_ops_and_no_arbitrary_sql(self):
        pipe=Mock(); pipe.initial={'autocommit':False}; pipe.call.return_value='safe-value'
        with patch.object(transport,'PrivatePipe',return_value=pipe): conn=transport.PipeConnection(CONFIG)
        self.assertEqual(conn.execute('SELECT current_database()').fetchone(),('safe-value',))
        pipe.call.assert_called_with('database',())
        pipe.call.reset_mock()
        with self.assertRaises(ValueError): conn.execute('DROP DATABASE anything')
        pipe.call.assert_not_called()
        conn.read_only=False; pipe.call.assert_called_once_with('write')
        with self.assertRaises(ValueError): conn.read_only=True
        conn.rollback(); conn.commit(); conn.close(); pipe.close.assert_called_once()

    def test_pipe_real_framing_mock_subprocess_no_secrets_in_command(self):
        process=Mock(); process.stdin=io.StringIO()
        process.stdout=io.StringIO(json.dumps({'ok':True,'value':{'database':DB}})+'\n'+
            json.dumps({'ok':True,'value':42})+'\n')
        with patch.object(transport.subprocess,'Popen',return_value=process) as spawn:
            pipe=transport.PrivatePipe(CONFIG,'controller')
            self.assertEqual(pipe.call('counts'),42)
            written=process.stdin.getvalue()
            pipe.close()
        self.assertIn('synthetic-private-marker',written)
        self.assertNotIn('synthetic-private-marker',str(spawn.call_args.args))
        self.assertEqual(spawn.call_args.kwargs['stderr'],transport.subprocess.DEVNULL)
        process.kill.assert_not_called()

    def test_malformed_or_denied_private_results_are_sanitized(self):
        pipe=transport.PrivatePipe.__new__(transport.PrivatePipe)
        pipe._queue=transport.queue.Queue()
        for line in ('', 'not json', '{"ok":false,"error":"synthetic-private-marker"}', 'x'*1048577):
            pipe._queue.put(line)
            with self.assertRaises(DispatchUncertain) as error: pipe._receive()
            self.assertNotIn('synthetic-private-marker',str(error.exception))

    def test_server_rejects_main_db_wrong_host_and_worker_identity(self):
        server=self.server(); self.assertEqual(server.validate(CONFIG),DB)
        for value in (dict(CONFIG,database='raa_wp2_validation'),
                dict(CONFIG,worker=dict(CONFIG['worker'],host='external.example')),
                dict(CONFIG,worker=dict(CONFIG['worker'],user='g0_user')),
                dict(CONFIG,worker=dict(CONFIG['worker'],dbname='postgres'))):
            with self.assertRaises(ValueError): server.validate(value)

    def test_server_read_frame_bounded_and_object_only(self):
        server=self.server()
        for text in ('[]\n','{}','x'*(server.LIMIT+1)+'\n'):
            with patch.object(server.sys,'stdin',io.StringIO(text)):
                with self.assertRaises(ValueError): server.read()
        with patch.object(server.sys,'stdin',io.StringIO('')): self.assertIsNone(server.read())

    def test_server_denies_unknown_ops_and_wrong_arity_without_sql(self):
        server=self.server(); conn=Mock(); conn.autocommit=False
        conn.execute.return_value.fetchone.return_value=(DB,)
        server.psycopg.connect.return_value=conn
        frames=[{'op':'shell','args':['anything']},{'op':'claim','args':['wrong-arity']},{'op':'close'}]
        output=io.StringIO()
        with patch.object(server,'read',side_effect=frames),redirect_stdout(output): server.worker(CONFIG)
        conn.execute.assert_called_once_with('SELECT current_database()')
        self.assertEqual(output.getvalue().count('operation-denied'),2)
        self.assertNotIn('synthetic-private-marker',output.getvalue())
        conn.close.assert_called_once()

    def test_server_eof_rolls_back_and_closes_connection(self):
        server=self.server(); conn=Mock(); conn.autocommit=False
        conn.execute.return_value.fetchone.return_value=(DB,)
        server.psycopg.connect.return_value=conn
        with patch.object(server,'read',return_value=None),redirect_stdout(io.StringIO()): server.worker(CONFIG)
        self.assertEqual(conn.rollback.call_count,2); conn.commit.assert_not_called(); conn.close.assert_called_once()


if __name__=='__main__': unittest.main()
