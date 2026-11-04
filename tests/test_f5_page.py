"""Saved P4 answer/citation integrity; no embeddings or model execution."""
import json
from pathlib import Path
import unittest
from test_f3_page import Evidence

ROOT=Path(__file__).resolve().parents[1]

class RagEvidence(Evidence):
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.reading=dict(attrs).get('id')=='rag-evidence'

class F5Tests(unittest.TestCase):
    def test_answers_and_exact_citations_match_retrieved_context(self):
        parser=RagEvidence();parser.feed((ROOT/'api/overview_assets/index.html').read_text(encoding='utf-8'))
        cases=json.loads(parser.data)
        self.assertEqual([c['execution_id'] for c in cases],[98,100,102])
        for c in cases:
            self.assertEqual(c['status'],'PASS');self.assertEqual(c['embedding_dimensions'],384)
            self.assertEqual(c['answer'],' '.join(c['model_response']['answer']))
            self.assertEqual(set(c['source_ids']),set(c['model_response']['source_ids']))
            self.assertTrue(c['question']);self.assertTrue(c['quotes'])
            for quote in c['quotes']:
                chunk=next(x for x in c['retrieved_chunks'] if x['chunk_id']==quote['chunk_id'])
                for field in ('text','source_id','source_path'):self.assertEqual(quote[field],chunk[field])
                self.assertIn(quote['chunk_id'],c['citations'])
                self.assertIn(quote['source_path'],('docs/KPI_DICTIONARY.md','docs/DATA_CONTRACT.md'))
                self.assertEqual(quote['url'],f"http://127.0.0.1:15690/workflow/p4-rag-core-v1/executions/{c['execution_id']}")
        self.assertGreaterEqual(len(cases[2]['source_ids']),2)
    def test_scoped_controls_disclosure_and_no_live_transport(self):
        html=(ROOT/'api/overview_assets/index.html').read_text(encoding='utf-8')
        section=html.split('<main id="knowledge-assistant"')[1].split('</main>')[0]
        self.assertEqual(section.count('data-rag-scenario='),3)
        self.assertEqual(section.count('Local portfolio demonstration'),1)
        self.assertNotIn('<details open',section)
        self.assertIn('id="knowledge-nav" href="#knowledge-assistant"',html)
        js=(ROOT/'api/overview_assets/overview.js').read_text(encoding='utf-8')
        for word in ('fetch(','innerHTML','XMLHttpRequest','sessionStorage','localStorage'):
            self.assertNotIn(word,js)
