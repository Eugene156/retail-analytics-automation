"""Private probe registry batching, no real credential/config access."""
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import wp4_portal_local


class RegistryTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'.local'/'wp4-auth-registry-tests'
        root.mkdir(parents=True,exist_ok=True)
        self.root=Path(tempfile.mkdtemp(prefix='registry-',dir=root))

    def test_concurrent_host_writers_keep_every_value_and_valid_json(self):
        target=self.root/'concurrent.json'
        values=[format(100+n,'064x') for n in range(24)]
        with patch.object(wp4_portal_local,'PROBES',target):
            with ThreadPoolExecutor(max_workers=4) as workers:
                list(workers.map(wp4_portal_local.retain,values))
            saved=json.loads(target.read_text())
            self.assertEqual(len(saved),48)
            self.assertTrue(all(v in saved and sha256(v.encode()).hexdigest() in saved for v in values))

    def test_concurrent_readers_never_observe_truncated_JSON(self):
        target=self.root/'readers.json';done=threading.Event();errors=[]
        with patch.object(wp4_portal_local,'PROBES',target):
            wp4_portal_local.retain('9'*64)
            def read():
                while not done.is_set():
                    try:wp4_portal_local.read_registry()
                    except Exception:errors.append(True)
                    time.sleep(.001)
            reader=threading.Thread(target=read);reader.start()
            try:
                for n in range(12):wp4_portal_local.retain(format(200+n,'064x'))
            finally:done.set();reader.join(timeout=5)
            self.assertFalse(reader.is_alive());self.assertEqual(errors,[])

    def test_explicit_repair_preserves_raw_corruption_and_complete_values(self):
        target=self.root/'broken.json';a,b='7'*64,'8'*64
        raw=(json.dumps([a])+json.dumps([b])).encode()
        target.write_bytes(raw)
        with patch.object(wp4_portal_local,'PROBES',target):
            self.assertEqual(wp4_portal_local.recover_probe_registry(),2)
            self.assertEqual(json.loads(target.read_text()),[a,b])
        self.assertEqual(next(self.root.glob('portal-test-secrets-corrupt-*.json')).read_bytes(),raw)

    def test_batch_preserves_prior_order_hashes_and_deduplicates(self):
        target=self.root/'probes.json'
        first,second='1'*64,'2'*64
        with patch.object(wp4_portal_local,'PROBES',target):
            wp4_portal_local.retain(first)
            wp4_portal_local.retain_many((first,second,second))
            self.assertEqual(json.loads(target.read_text()),
                [first,sha256(first.encode()).hexdigest(),second,sha256(second.encode()).hexdigest()])

    def test_single_registration_matches_batch(self):
        a,b=self.root/'single.json',self.root/'batch.json'
        values=('3'*64,'4'*64,'3'*64)
        with patch.object(wp4_portal_local,'PROBES',a):
            for value in values:
                wp4_portal_local.retain(value)
        with patch.object(wp4_portal_local,'PROBES',b):
            wp4_portal_local.retain_many(values)
        self.assertEqual(a.read_bytes(),b.read_bytes())


if __name__=='__main__':
    unittest.main()
