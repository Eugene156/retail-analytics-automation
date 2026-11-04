"""Offline replay of reviewed demo evidence; no Docker, network or inference.

Expectations reuse SQL/MCP facts and P4 policy anchors. This is a retrospective
diagnostic suite, not a held-out benchmark or a new live execution receipt.
"""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import re

import check_publication as publication
from p4_workflows import ANSWER_RULES, documents

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ('P2-KPI', 'p2_ai_agent', 28, {'Get_Sales_KPIs'}, ('79.42', '1349.45', '33')),
    ('P2-Quality', 'p2_ai_agent', 24, {'Get_Data_Quality'}, ('quality_zero',)),
    ('P2-Combined', 'p2_ai_agent', 26, {'Get_Sales_KPIs', 'Get_Data_Quality'},
     ('79.42', '1349.45', '41', '1270.03', 'quality_zero')),
    ('P3-KPI', 'p3_mcp_agent', 32, {'get_sales_kpis'}, ('79.42', '1349.45', '33')),
    ('P3-Combined', 'p3_mcp_agent', 41, {'get_sales_kpis', 'get_data_quality'}, ()),
    ('P4-KPI', 'p4_rag_runtime', 80, None, ('net', 'adjustments')),
    ('P4-Cancellations', 'p4_rag_runtime', 82, None, ('cancellation', 'physical')),
    ('P4-Combined', 'p4_rag_runtime', 84, None, ('net', 'adjustments', 'missing', 'coverage')),
]
METRICS = ('Tool Selection Accuracy', 'Factual Correctness', 'Citation Validity', 'Schema Compliance')


def load_reviewed():
    names = {case[1] for case in CASES} | {'p3_mcp_discovery'}
    protected = publication.local_secrets()
    evidence = {}
    for name in sorted(names):
        path = f'evidence/{name}.json'
        if publication.inspect(path, protected):
            raise ValueError('Evidence publication preflight failed; content suppressed')
        evidence[name] = json.loads((ROOT / path).read_text())
    return evidence


def record(evidence, name, execution):
    return deepcopy(next(e for e in evidence[name]['executions'] if e['id'] == execution))


def mcp_bodies(entry):
    bodies = {}
    for step in entry.get('mcp_history', []):
        tool = step['inputOverride']['ai_tool'][0][0]['json']['tool']
        name = tool.removeprefix('MCP_Client_Tool_')
        body = step['data']['ai_tool'][0][0]['json']['structuredContent']
        assert body['access'] == 'read-only' and body['schema_version'] == 'p2-read-tool-v1'
        bodies[name] = body
    return bodies


def labels_valid(answer, bodies):
    fields = {}
    if 'get_sales_kpis' in bodies:
        k = bodies['get_sales_kpis']['kpis']
        fields.update({'Sale rows': k['sale_rows'], 'Net recorded sales': k['net_recorded_sales_gbp'],
                       'Gross sales': k['sales_value_gbp'], 'Cancellation rows': k['cancellation_rows'],
                       'Cancellation magnitude': k['cancellation_magnitude_gbp']})
    if 'get_data_quality' in bodies:
        q = bodies['get_data_quality']
        fields.update({'Quality findings': q['quality']['finding_rows'],
                       'Missing customer sale rows': q['missing_customer_sale_rows']})
    schema, facts = True, True
    for label, expected in fields.items():
        matches = re.findall(r'(?im)^' + re.escape(label) + r':\s*(?:GBP\s+)?(\d+(?:\.\d+)?)\s*$', answer)
        schema = schema and len(matches) == 1
        facts = facts and len(matches) == 1 and Decimal(matches[0]) == Decimal(str(expected))
    return schema, facts


def evaluate(case, entry):
    cid, _, _, expected_tools, required = case
    result = dict.fromkeys(METRICS)
    if expected_tools is not None:
        tools = entry.get('tools_used', [])
        result[METRICS[0]] = set(tools) == expected_tools
        if cid.startswith('P3'):
            bodies = mcp_bodies(entry)
            calls = {s['action']['tool'].removeprefix('MCP_Client_Tool_')
                     for s in entry.get('intermediateSteps', [])}
            result[METRICS[0]] &= set(bodies) == expected_tools == calls
        answer = entry.get('answer', '')
        if cid == 'P3-Combined':
            result[METRICS[3]], result[METRICS[1]] = labels_valid(answer, bodies)
        else:
            # Bounded required-value/zero-finding checks; not all-prose validation.
            numbers = re.findall(r'(?<!\w)\d+(?:\.\d+)?', answer.replace(',', ''))
            result[METRICS[1]] = all(
                bool(re.search(r'(?i)(no data quality issues|no findings|quality.{0,30}0|all flagged rows.{0,80}zero)', answer))
                if value == 'quality_zero' else value in numbers for value in required)
        result[METRICS[1]] &= not bool(re.search(r'(?i)no cancellations', answer))
    else:
        output = entry.get('model_response', {})
        schema = (isinstance(output, dict) and set(output) == {'answer', 'source_ids'}
                  and isinstance(output['answer'], list) and bool(output['answer'])
                  and all(isinstance(x, str) for x in output['answer'])
                  and isinstance(output['source_ids'], list)
                  and all(isinstance(x, str) for x in output['source_ids'])
                  and len(set(output['answer'])) == len(output['answer'])
                  and len(set(output['source_ids'])) == len(output['source_ids']))
        result[METRICS[3]] = schema
        chunks = entry.get('retrieved_chunks', [])
        sources = set(output.get('source_ids', [])) if isinstance(output, dict) else set()
        rules = {r['id']: r for r in ANSWER_RULES}
        used_sources = {support['source_id'] for rid in required for support in rules[rid]['evidence']}
        facts = (schema and output['answer'] == [rules[rid]['answer'] for rid in required]
                 and entry.get('answer') == ' '.join(output['answer']) and sources == used_sources)
        for rid in required:
            for support in rules[rid]['evidence']:
                facts &= any(c['source_id'] == support['source_id']
                             and all(a in c['text'] for a in support['anchors']) for c in chunks)
        result[METRICS[1]] = bool(facts)
        quotes = entry.get('quotes', [])
        corpus = {d['source_id']: d for d in documents()}
        citations = bool(quotes) and sources <= {c['source_id'] for c in chunks}
        for chunk in chunks:
            doc = corpus.get(chunk.get('source_id'))
            citations &= bool(doc and chunk.get('source_path') == doc['source_path']
                              and chunk.get('document_sha256') == doc['document_sha256']
                              and chunk.get('text', '') and chunk['text'] in doc['text'])
        citations &= {q['source_id'] for q in quotes} == sources
        citations &= set(entry.get('source_ids', [])) == sources
        citations &= entry.get('citations') == [q['chunk_id'] for q in quotes]
        for quote in quotes:
            citations &= any(all(quote.get(k) == c.get(k) for k in
                                ('text', 'chunk_id', 'source_id', 'source_path')) for c in chunks)
            citations &= quote.get('url') == f"http://127.0.0.1:15690/workflow/p4-rag-core-v1/executions/{entry['id']}"
        result[METRICS[2]] = bool(citations)
    result['Pass Rate'] = all(v for v in result.values() if v is not None)
    return result


def reference_facts_valid(evidence):
    bodies = {r['name']: r['response'] for r in evidence['p3_mcp_discovery']['requests']}
    k, q = bodies['get_sales_kpis']['kpis'], bodies['get_data_quality']['quality']
    assert (Decimal(k['net_recorded_sales_gbp']), Decimal(k['sales_value_gbp']),
            k['sale_rows'], k['cancellation_rows'], Decimal(k['cancellation_magnitude_gbp']),
            q['finding_rows']) == (Decimal('79.42'), Decimal('1349.45'), 33, 41, Decimal('1270.03'), 0)


def report(evidence):
    reference_facts_valid(evidence)
    rows = [(case, evaluate(case, record(evidence, case[1], case[2]))) for case in CASES]
    lines = ['# AI demo evaluation report', '',
             'Offline replay date: 2026-10-11. No new LLM/workflow/Docker run.', '',
             '## Cases and actual replay results', '',
             '| Case | Historical core execution | Tools | Facts | Citations | Schema | Case |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    show = lambda v: 'N/A' if v is None else 'PASS' if v else 'FAIL'
    for case, result in rows:
        lines.append(f'| {case[0]} | {case[2]} | ' + ' | '.join(show(result[m]) for m in (*METRICS, 'Pass Rate')) + ' |')
    lines += ['', '## Metrics and denominators', '']
    for metric in (*METRICS, 'Pass Rate'):
        applicable = [r[metric] for _, r in rows if r[metric] is not None]
        lines.append(f'- {metric}: {sum(applicable)}/{len(applicable)} ({100*sum(applicable)/len(applicable):.1f}%).')
    lines += ['', '## Method and evidence', '',
              'Publication preflight checks the three existing evidence JSON files and MCP',
              'discovery against known local secrets/provider patterns before reading results.',
              'No raw execution export or new private log is generated. Inputs:',
              '[P2](../evidence/p2_ai_agent.json), [P3](../evidence/p3_mcp_agent.json),',
              '[P4](../evidence/p4_rag_runtime.json), [MCP facts](../evidence/p3_mcp_discovery.json).', '',
              '| Case | Frozen expectation |',
              '| --- | --- |',
              '| P2-KPI | KPI only; net79.42, sales1349.45, sale rows33 |',
              '| P2-Quality | Data Quality only; zero findings |',
              '| P2-Combined | Both tools; net79.42, sales1349.45, cancellations41/1270.03; zero findings |',
              '| P3-KPI | MCP KPI only; net79.42, sales1349.45, sale rows33 |',
              '| P3-Combined | Both MCP tools; all seven labelled facts match responses |',
              '| P4-KPI | Net sales formula and adjustment exclusion; kpi-dictionary |',
              '| P4-Cancellations | Cancellation versus invalid rows; no inferred return/refund; both sources |',
              '| P4-Combined | Net/adjustments, missing IDs retained, row coverage; both sources |', '',
              'Tool Selection Accuracy is exact expected-set agreement per applicable case.',
              'P2 uses saved tools_used summaries (not independent reinspection of tool calls);',
              'P3 additionally checks MCP response bodies and agent intermediate tool actions.',
              'P4 retrieves before the agent, so tool selection is N/A.', '',
              'Factual Correctness means bounded required-fact compliance, not all-prose accuracy.',
              'P2 and historical P3 single-tool answers check required numeric tokens/zero-quality',
              'phrases against fixed-period SQL/MCP reference values. These limited checks cannot',
              'prove number-to-label binding or catch every additional unsupported claim. Current',
              'P3 combined output uses exact labels/Decimal comparison against actual MCP bodies.',
              'P4 reuses existing ANSWER_RULES and required-topic anchors in actual retrieved',
              'chunks; model sentences must be unchanged and match the bounded policy vocabulary.', '',
              'Citation Validity requires actual retrieved source/chunk membership, exact quote',
              'text/path, matching source_ids and execution URL. Retrieved text/path/hash must',
              'also match the existing policy corpus rebuilt from source documents; only P4',
              'has applicable citations.',
              'Schema Compliance checks P4 model JSON shape and P3 combined label contract.',
              'P2 and older P3 single-tool JSON schema proof is unavailable: N/A, not PASS.',
              'Pass Rate requires every applicable metric; N/A never contributes to denominators.', '',
              'Historical P3 execution38 says "No cancellations" despite41 cancellations.',
              'It is retained as a rejection regression, not silently relabelled by its stored',
              'PASS status. The final repair execution41 is the combined acceptance case.', '',
              '## Offline and live separation', '',
              'Run `python scripts/evaluate_ai_demo.py` to replay; add `--report` to regenerate',
              'this report. CI runs only offline pytest checks of replay and corrupted cases.',
              'Existing G0 evaluator design (fixed cases, explicit failures and denominators)',
              'is reused conceptually; it is not invoked because it performs live inference.', '',
              'Fresh live evaluation remains pending separate owner authorization. Manually run',
              'P2 KPI/quality/combined, P3 single/combined (including41 and GBP1270.03), and',
              'P4 KPI/cancellations/combined, one at a time. Use the eight case expectations',
              'in CASES, preserve failed runs, record model/workflow versions and elapsed time,',
              'then apply existing check_p2_demo/check_p3_demo/check_p4_demo safety checks only',
              'after reviewing their operations and obtaining required Docker permissions.',
              'No live executor is installed in CI; this offline command never launches one.', '',
              'Manual parents: [P2](http://127.0.0.1:15690/workflow/p2-read-agent-demo-v1),',
              '[P3](http://127.0.0.1:15690/workflow/p3-mcp-agent-demo-v1),',
              '[P4](http://127.0.0.1:15690/workflow/p4-rag-demo-v1). After authorization, edit',
              'the Question node and Execute workflow; do not execute guarded cores directly.',
              'Use saved P2/P4 questions from the selected evidence entries. For P3 ask',
              '"What are the sales KPIs for the demo period?" then "Summarize sales KPIs,',
              'cancellations and data quality for the demo period." Fresh P3 single-tool output',
              'must satisfy the current five KPI labels, beyond the older execution32 checks.', '',
              '## Limitations', '',
              'Eight selected historical development demonstrations, not held-out cases or a',
              'statistical benchmark. Model/prompt versions differ between old P3 single and',
              'repaired combined cases. Saved summaries do not prove current runtime behavior.',
              'P4 has a finite policy corpus; live abstention, hostile input, nondeterministic',
              'reruns and broad retrieval recall/precision are not evaluated here. Localhost',
              'citation URLs identify historical runs and are not public clickable evidence.',
              'A 100% replay result is not a claim of general model accuracy or production readiness.', '']
    return '\n'.join(lines), rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', action='store_true', help='Regenerate bounded Markdown report')
    args = parser.parse_args()
    text, rows = report(load_reviewed())
    if args.report:
        (ROOT / 'docs/AI_EVALUATION_REPORT.md').write_text(text, encoding='utf-8')
    print(f'Offline historical replay: {sum(r["Pass Rate"] for _, r in rows)}/{len(rows)} PASS; live runs=0')
    return int(not all(r['Pass Rate'] for _, r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
