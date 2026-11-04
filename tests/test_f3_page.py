"""Focused static evidence contracts; browser checks cover scenario interaction."""
import json
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class Evidence(HTMLParser):
    def __init__(self):
        super().__init__();self.reading=False;self.data=''
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('id')=='agent-evidence':self.reading=True
    def handle_endtag(self,tag):
        if tag=='script':self.reading=False
    def handle_data(self,data):
        if self.reading:self.data+=data

class F3Tests(unittest.TestCase):
    def test_three_real_evidence_cases_and_actual_tool_calls(self):
        parser=Evidence();parser.feed((ROOT/'api/overview_assets/index.html').read_text(encoding='utf-8'))
        cases=json.loads(parser.data)
        self.assertEqual([c['execution_id'] for c in cases],[88,90,104])
        self.assertEqual([set(t['tool'] for t in c['tool_calls']) for c in cases],
          [{'Get_Sales_KPIs'},{'Get_Data_Quality'},{'Get_Sales_KPIs','Get_Data_Quality'}])
        for c in cases:
            self.assertTrue(c['model_response']);self.assertTrue(c['validated_answer'])
            self.assertTrue(all(t['result'] for t in c['tool_calls']))
    def test_presentation_has_no_execution_or_html_injection_transport(self):
        js=(ROOT/'api/overview_assets/overview.js').read_text(encoding='utf-8')
        for forbidden in ('fetch(', 'XMLHttpRequest','innerHTML','localStorage','sessionStorage','Bearer '):
            self.assertNotIn(forbidden,js)
        page=(ROOT/'api/overview_assets/index.html').read_text(encoding='utf-8')
        self.assertEqual(page.count('data-scenario='),3)
        self.assertIn('SAVED EXECUTIONS',page)
        self.assertEqual(page.split('<main id="ai-agent"')[1].split('</main>')[0].count('Local portfolio demonstration'),1)
