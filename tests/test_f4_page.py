"""Focused static contracts for saved MCP scenarios; no live workflows."""
import json
from pathlib import Path
import unittest
from test_f3_page import Evidence

ROOT=Path(__file__).resolve().parents[1]

class McpEvidence(Evidence):
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.reading=dict(attrs).get('id')=='mcp-evidence'

class F4Tests(unittest.TestCase):
    def test_real_execution_ids_and_mcp_results(self):
        p=McpEvidence();p.feed((ROOT/'api/overview_assets/index.html').read_text(encoding='utf-8'))
        cases=json.loads(p.data)
        self.assertEqual([c['execution_id'] for c in cases],[94,106])
        self.assertEqual([{x['mcp_tool'] for x in c['calls']} for c in cases],
                         [{'get_sales_kpis'},{'get_sales_kpis','get_data_quality'}])
        for case in cases:
            self.assertEqual(case['status'],'PASS')
            self.assertTrue(case['question']);self.assertTrue(case['model_output']);self.assertTrue(case['answer'])
            for call in case['calls']:
                self.assertEqual(call['analytics']['access'],'read-only')
                self.assertEqual(call['analytics'],json.loads(call['raw_response'][0]['response'][0]['text']))
                self.assertEqual(call['client_tool'],'MCP_Client_Tool_'+call['mcp_tool'])
    def test_disclosure_collapsed_payloads_and_navigation(self):
        page=(ROOT/'api/overview_assets/index.html').read_text(encoding='utf-8')
        fragment=page.split('<main id="mcp-analytics"')[1].split('</main>')[0]
        self.assertEqual(fragment.count('Local portfolio demonstration'),1)
        self.assertEqual(fragment.count('data-mcp-scenario='),2)
        self.assertNotIn('<details open',fragment)
        self.assertIn('n8n MCP Client',fragment);self.assertIn('MCP Server',fragment)
        self.assertIn('id="mcp-nav" href="#mcp-analytics"',page)
        js=(ROOT/'api/overview_assets/overview.js').read_text(encoding='utf-8')
        self.assertIn('detail.open=false',js)
        for forbidden in ('fetch(', 'XMLHttpRequest','innerHTML','localStorage','sessionStorage'):
            self.assertNotIn(forbidden,js)
