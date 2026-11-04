"""Opt-in isolated native owner run; bridge-only mode never calls NTFS adapter."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from check_wp4_dispatch_local import provision


def main(native=False):
    if native and os.name!='nt': raise RuntimeError('Native Windows owner run required')
    config=provision()
    spec=importlib.util.spec_from_file_location('wp4_native_suite',ROOT/'tests/wp4_dispatch_native_suite.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result=module.run(config,native)
    print('Test database/login/fixtures retained: '+config['database'])
    print(('PASS' if result['passed'] else 'FAIL')+'|'+result['evidence']+'|'+str(result['tests_run']))
    if not result['passed']:
        print('FAIL|test-names|'+','.join(result['failed_tests']))
        print('FAIL|exception-types|'+','.join(result['error_types']))
        raise RuntimeError('Isolated harness failed')
    print('BLOCKED|real-dispatch|pause-deadline-fencing-unverified-or-counterexample')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--native',action='store_true',help='Owner-run real Windows files in synthetic roots; includes known deadline diagnostic')
    group.add_argument('--bridge-only',action='store_true',help='Test private IPC/real SQL with in-memory files; no native file call')
    args=parser.parse_args()
    try: main(args.native)
    except (RuntimeError,ValueError,OSError):
        raise SystemExit('FAIL|isolated-harness|details-suppressed-to-protect-secrets') from None
