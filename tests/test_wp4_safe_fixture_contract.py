"""I1 offline boundary tests. Dummy strings never authenticate native resources."""
from dataclasses import replace,FrozenInstanceError
import json
from hashlib import sha256
import pickle
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import UUID

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wp4_safe_fixture_contract as x

KEY='42b4d3b2-98d8-4d0f-a7fd-25c3c66466ad'
OTHER='c1a891b4-8760-4e33-a9a5-aed6a2f12ac7'


class I1Tests(unittest.TestCase):
    def context(self,key=KEY,purpose='source-build'):
        return x.ScopedContext.from_contract(x.canonical(x.proposal(key)),purpose)

    def test_reproducible_scaffold_and_bound_alias(self):
        raw=x.canonical(x.proposal(KEY));self.assertEqual(raw,x.canonical(x.proposal(KEY)))
        record=x.validate(raw);mapping=record['identity_mapping']
        self.assertEqual(mapping['report']['isolated_legacy_alias'],x.LEGACY_CASE)
        self.assertEqual(mapping['report']['logical_case_id'],x.PUBLIC_CASE)
        self.assertEqual(mapping['report']['alias_scope_checkpoint'],KEY)
        self.assertEqual(len(set(mapping['fresh'].values())),5)
        self.assertNotEqual(x.mappings(KEY),x.mappings(OTHER))

    def test_reserved_checkpoint_collisions(self):
        for key in (x.PUBLIC_CHECKPOINT,x.PUBLIC_CASE,x.LEGACY_CASE,x.ORIGINAL_CHECKPOINT):
            with self.subTest(key=key),self.assertRaises(x.FixtureDenied):x.proposal(key)

    def test_invalid_uuid_and_direct_collision(self):
        for key in ('external','0'*32,'00000000-0000-0000-0000-000000000000',KEY.upper(),1):
            with self.subTest(key=key),self.assertRaises(x.FixtureDenied):x.proposal(key)
        with patch.object(x,'derived',return_value=KEY):
            with self.assertRaises(x.FixtureDenied):x.proposal(KEY)

    def test_manifest_wrong_profile_source_mapping_flags_and_native_evidence(self):
        mutations=[lambda v:v.update(profile='production'),lambda v:v['source'].update(workbook_sha256='a'*64),
            lambda v:v['identity_mapping']['report'].update(isolated_legacy_alias=OTHER),
            lambda v:v.update(application_writers_admitted=True),lambda v:v.update(external_dispatch_allowed=True),
            lambda v:v['native_evidence'].update(catalog='verified'),lambda v:v['authority_policy'].update(outbox=1),
            lambda v:v['authority_policy'].update(sessions=False),lambda v:v['materialization_recipe'].update(sha256='b'*64)]
        for mutation in mutations:
            value=x.proposal(KEY);mutation(value)
            with self.subTest(mutation=mutations.index(mutation)),self.assertRaises(x.FixtureDenied):x.validate(x.canonical(value))

    def test_hidden_duplicate_json_unknown_field_and_noncanonical_rejected(self):
        raw=x.canonical(x.proposal(KEY))
        for data in (b'{"profile":"hidden",'+raw[1:],raw+b' ',b'[]',b'{}',b'\xff',b'x'*16385):
            with self.assertRaises(x.FixtureDenied):x.validate(data)
        value=x.proposal(KEY);value['token']='offline-only-dummy'
        with self.assertRaises(x.FixtureDenied):x.validate(x.canonical(value))

    def test_contract_separation(self):
        import wp4_checkpoint_manifest as old
        with self.assertRaises(old.ManifestError):old.validate(x.proposal(KEY),{})
        with self.assertRaises(x.FixtureDenied):x.validate(x.canonical({'contract_version':old.VERSION,'checkpoint_id':KEY}))
        with self.assertRaises(x.FixtureDenied):x.validate(x.canonical({'contract_version':'wp4-public-offline-checkpoint-v1','checkpoint_id':x.PUBLIC_CHECKPOINT}))

    def test_context_exact_targets_and_no_native_admission(self):
        context=self.context()
        for kind in ('container','network','volume','database'):
            self.assertEqual(context.request(kind,dict(context.target_items)[kind]),dict(context.target_items)[kind])
        with self.assertRaises(x.FixtureDenied):context.admit_native()
        with self.assertRaises(FrozenInstanceError):context.checkpoint_id=OTHER

    def test_external_resources_wrong_kind_context_and_cross_fixture(self):
        context=self.context()
        for kind,value in [('url','https://external.invalid'),('container','raa-g0-postgres-1'),
            ('volume','working-data'),('database','n8n'),('network','raa-g0_default')]:
            with self.subTest(kind=kind),self.assertRaises(x.FixtureDenied):context.request(kind,value)
        for invalid in (replace(context,checkpoint_id=OTHER),replace(context,purpose='production'),
                        replace(context,contract_sha256='f'*64),replace(context,target_items=(('container','external'),))):
            with self.assertRaises(x.FixtureDenied):invalid.checked()
        with self.assertRaises(x.FixtureDenied):context.request('container',dict(self.context(OTHER).target_items)['container'])
        tampered=tuple((k,0 if v is False else v) for k,v in context.target_items)
        with self.assertRaises(x.FixtureDenied):replace(context,target_items=tampered).checked()

    def test_secret_provider_wrong_context_missing_closed_no_fallback(self):
        context=self.context();provider=x.SyntheticSecrets(context,{'owner-token':b'offline-dummy-owner-token'})
        self.assertEqual(provider.get(context,'owner-token'),b'offline-dummy-owner-token')
        for other in (self.context(OTHER),self.context(purpose='reference-build'),None):
            with self.assertRaises(x.FixtureDenied):provider.get(other,'owner-token')
        for name in ('owner-digest','dsn','https://external.invalid',None):
            with self.assertRaises(x.FixtureDenied):provider.get(context,name)
        provider.close()
        with self.assertRaises(x.FixtureDenied):provider.get(context,'owner-token')
        with self.assertRaises(x.FixtureDenied):provider.check_capture(context,b'aggregate-only')
        with self.assertRaises(x.FixtureDenied):x.SyntheticSecrets(context,{}).check_capture(context,b'aggregate-only')

    def test_secret_configuration_and_input_copy(self):
        context=self.context()
        for values in ({'dsn':b'offline-dummy-dsn'},{'owner-token':b'short'},{'owner-token':'offline-dummy-token'},
            {'owner-token':b'offline-dummy-token\n'},{'owner-token':b'offline-dummy-token','owner-digest':b'offline-dummy-token'}):
            with self.assertRaises(x.FixtureDenied):x.SyntheticSecrets(context,values)
        values={'owner-token':b'offline-dummy-owner-token'};provider=x.SyntheticSecrets(context,values);values.clear()
        self.assertEqual(provider.get(context,'owner-token'),b'offline-dummy-owner-token')

    def test_capture_representation_exception_and_pickle_no_secret_output(self):
        context=self.context();dummy=b'offline-dummy-owner-digest';provider=x.SyntheticSecrets(context,{'owner-digest':dummy})
        self.assertNotIn(dummy.decode(),repr(provider));self.assertIsNone(provider.check_capture(context,b'aggregate-only'))
        for data in (b'prefix '+dummy,b'SCRAM-SHA-256$dummy',b'x'*1048577,'text'):
            with self.assertRaises(x.FixtureDenied) as error:provider.check_capture(context,data)
            self.assertNotIn(dummy.decode(),str(error.exception))
        with self.assertRaises(x.FixtureDenied):pickle.dumps(provider)

    def test_derived_owner_digest_filtered_without_explicit_registration(self):
        context=self.context();token=b'offline-dummy-owner-token'
        provider=x.SyntheticSecrets(context,{'owner-token':token})
        with self.assertRaises(x.FixtureDenied):provider.check_capture(context,sha256(token).hexdigest().encode())
        with self.assertRaises(x.FixtureDenied):provider.get(context,'owner-digest')

    def test_explicit_owner_token_digest_consistency(self):
        context=self.context();token=b'offline-dummy-owner-token';digest=sha256(token).hexdigest().encode()
        provider=x.SyntheticSecrets(context,{'owner-token':token,'owner-digest':digest})
        self.assertEqual(provider.get(context,'owner-digest'),digest)
        with self.assertRaises(x.FixtureDenied):x.SyntheticSecrets(context,{'owner-token':token,'owner-digest':b'offline-dummy-wrong-digest'})

    def test_no_implicit_io_environment_minting_or_transport(self):
        import builtins,os,secrets,subprocess
        with patch.object(builtins,'open',side_effect=AssertionError('file read forbidden')),\
             patch.object(os,'getenv',side_effect=AssertionError('environment forbidden')),\
             patch.object(secrets,'token_bytes',side_effect=AssertionError('minting forbidden')),\
             patch.object(subprocess,'run',side_effect=AssertionError('transport forbidden')):
            context=self.context();provider=x.SyntheticSecrets(context,{'owner-token':b'offline-dummy-owner-token'})
            provider.get(context,'owner-token');provider.check_capture(context,b'aggregate-only')


if __name__=='__main__':unittest.main()
