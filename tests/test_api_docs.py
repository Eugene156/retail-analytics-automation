"""Portable minimum contract/export checks, not a full OpenAPI validator."""
import ast
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / 'docs' / name).read_text())


def requests(collection):
    return [item for folder in collection['item'] for item in folder['item']]


def shape(value, schema, spec):
    """Only the schema features used by these documented example responses."""
    if '$ref' in schema:
        schema = spec['components']['schemas'][schema['$ref'].split('/')[-1]]
    kinds = schema.get('type', [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    matches = {'object': isinstance(value, dict), 'string': isinstance(value, str),
               'number': type(value) in (int, float), 'integer': type(value) is int,
               'null': value is None, 'array': isinstance(value, list)}
    assert not kinds or any(matches.get(k, False) for k in kinds)
    assert 'enum' not in schema or value in schema['enum']
    assert 'const' not in schema or value == schema['const']
    if isinstance(value, dict):
        assert set(schema.get('required', [])) <= set(value)
        if schema.get('additionalProperties') is False:
            assert set(value) <= set(schema.get('properties', {}))
        for key, child in schema.get('properties', {}).items():
            if key in value:
                shape(value[key], child, spec)


class ApiDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = read('openapi_demo.json')
        cls.collection = read('postman_collection.json')
        cls.environment = read('postman_environment.template.json')

    def test_projection_matches_existing_routes(self):
        tree = ast.parse((ROOT / 'api/main.py').read_text())
        routes = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ('get', 'post') and node.args and isinstance(node.args[0], ast.Constant):
                    routes.add((node.args[0].value, node.func.attr))
        self.assertEqual(self.spec['openapi'], '3.1.0')
        self.assertEqual(len(self.spec['paths']), 8)
        for path, methods in self.spec['paths'].items():
            self.assertFalse(any(x in path for x in ('/review/', 'approval', 'portal', 'publish', 'mcp', '/p2/')))
            for method in methods:
                self.assertIn((path, method), routes)

    def test_refs_and_minimum_responses(self):
        def walk(value):
            if isinstance(value, dict):
                if '$ref' in value:
                    self.assertTrue(value['$ref'].startswith('#/components/schemas/'))
                    self.assertIn(value['$ref'].split('/')[-1], self.spec['components']['schemas'])
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(self.spec)
        for path, methods in self.spec['paths'].items():
            for op in methods.values():
                self.assertIn('200', op['responses'])
                if path != '/healthz':
                    self.assertIn('401', op['responses'])
        self.assertEqual(self.spec['components']['schemas']['ComparisonReport']['required'],
                         ['schema_version', 'current_period', 'prior_period', 'changes'])

    def test_security_and_mutation_marks(self):
        changes = []
        for path, methods in self.spec['paths'].items():
            for method, op in methods.items():
                self.assertEqual(op['security'], [] if path == '/healthz' else [{'CalculationToken': []}])
                if op['x-state-changing']: changes.append((path, method))
        self.assertEqual(changes, [('/api/v1/report-requests', 'post')])
        request = self.spec['paths']['/api/v1/report-requests']['post']
        self.assertEqual(request['parameters'][0]['name'], 'Idempotency-Key')
        self.assertIn('202', request['responses'])
        self.assertIn('409', request['responses'])

    def test_request_schema_and_examples(self):
        schema = self.spec['components']['schemas']['CalculationRequest']
        tree = ast.parse((ROOT / 'api/main.py').read_text())
        source_hash = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == 'SOURCE_HASH' for t in n.targets))
        self.assertEqual(schema['properties']['source_file_sha256']['const'], source_hash)
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(len(schema['required']), 5)
        for path in ('/api/v1/calculations/comparison', '/api/v1/report-requests'):
            content = self.spec['paths'][path]['post']['requestBody']['content']['application/json']
            shape(content['example'], schema, self.spec)

    def test_collection_method_and_path_alignment(self):
        items = requests(self.collection)
        self.assertEqual(len(items), 10)
        self.assertEqual(sum(i['request']['method'] == 'GET' for i in items), 7)
        self.assertEqual(sum(i['request']['method'] == 'POST' for i in items), 3)
        self.assertEqual(self.collection['info']['schema'],
                         'https://schema.getpostman.com/json/collection/v2.1.0/collection.json')
        for item in items:
            req = item['request']
            path = req['url'].removeprefix('{{base_url}}').replace('{{case_id}}', '{case_id}').replace('{{revision}}', '{revision}')
            self.assertIn(req['method'].lower(), self.spec['paths'][path])

    def test_blank_credentials_and_variables(self):
        values = {v['key']: v['value'] for v in self.environment['values']}
        self.assertEqual(values['api_token'], '')
        self.assertEqual(values['allow_state_changes'], 'false')
        self.assertEqual(values['demo_target_confirmed'], 'false')
        self.assertEqual(values['case_id'], '')
        self.assertEqual(values['idempotency_key'], '')
        self.assertEqual(self.collection['auth']['bearer'][0]['value'], '{{api_token}}')
        for item in requests(self.collection):
            self.assertTrue(item['request']['url'].startswith('{{base_url}}/'))
            for var in re.findall(r'{{(.*?)}}', json.dumps(item['request'])):
                self.assertIn(var, values)

    def test_default_skip_guards_and_assertions(self):
        guard = '\n'.join(self.collection['event'][0]['script']['exec'])
        self.assertIn('127', guard)
        self.assertIn('pm.execution.skipRequest()', guard)
        folder = self.collection['item'][2]
        self.assertIn('STATE CHANGING', folder['name'])
        guard = '\n'.join(folder['event'][0]['script']['exec'])
        for marker in ('allow_state_changes', 'demo_target_confirmed', 'idempotency_key', 'pm.execution.skipRequest()'):
            self.assertIn(marker, guard)
        for item in requests(self.collection):
            self.assertIn('pm.response.code', '\n'.join(item['event'][0]['script']['exec']))
            self.assertTrue(item['response'][0]['name'].startswith('SYNTHETIC'))

    def test_saved_response_shapes(self):
        for item in requests(self.collection):
            req = item['request']
            path = req['url'].removeprefix('{{base_url}}').replace('{{case_id}}', '{case_id}').replace('{{revision}}', '{revision}')
            op = self.spec['paths'][path][req['method'].lower()]
            example = item['response'][0]
            if 'text/html' in example['header'][0]['value']: continue
            schema = op['responses'][str(example['code'])]['content']['application/json']['schema']
            shape(json.loads(example['body']), schema, self.spec)


if __name__ == '__main__':
    unittest.main()
