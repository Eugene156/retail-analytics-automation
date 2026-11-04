"""Focused source parity checks for the historical API/CI interface."""
import json
from pathlib import Path
import unittest
from test_f3_page import Evidence

ROOT=Path(__file__).resolve().parents[1]

class EngineeringEvidence(Evidence):
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.reading=dict(attrs).get('id')=='engineering-evidence'

class F6Tests(unittest.TestCase):
    def data(self):
        html=(ROOT/'api/overview_assets/index.html').read_text(encoding='utf-8')
        p=EngineeringEvidence();p.feed(html)
        return html,json.loads(p.data)
    def test_embedded_artifacts_match_repository_and_blank_secrets(self):
        _,data=self.data()
        self.assertEqual(data['spec'],json.loads((ROOT/'docs/openapi_demo.json').read_text(encoding='utf-8')))
        self.assertEqual(len(data['spec']['paths']),8)
        for name,content in data['artifacts'].items():
            self.assertEqual(content,(ROOT/'docs'/name).read_text(encoding='utf-8'))
        env=json.loads(data['artifacts']['postman_environment.template.json'])
        self.assertEqual(next(v['value'] for v in env['values'] if v['key']=='api_token'),'')
        self.assertEqual(data['ci'],(ROOT/'.github/workflows/ci.yml').read_text())
        self.assertEqual(data['ci_requirements'],(ROOT/'config/ci-requirements.txt').read_text())
        self.assertEqual(data['ci'].split('python -m pytest -q ')[1].count('tests/'),6)
    def test_sections_status_limits_and_no_live_calls(self):
        html,_=self.data();section=html.split('<main id="api-ci"')[1].split('</main>')[0]
        self.assertEqual(section.count('data-engineering-section='),5)
        self.assertEqual(section.count('Local portfolio demonstration'),1)
        self.assertIn('hosted run unverified',section)
        self.assertIn('No automated deployment/CD pipeline',section)
        self.assertIn('not a fresh run or a coverage percentage',section)
        self.assertNotIn('<details open',section)
        self.assertIn('id="engineering-nav" href="#api-ci"',html)
        js=(ROOT/'api/overview_assets/overview.js').read_text(encoding='utf-8')
        for word in ('fetch(','innerHTML','XMLHttpRequest','sessionStorage','localStorage'):
            self.assertNotIn(word,js)
