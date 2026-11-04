"""Offline historical replay and false-positive regressions; no live services."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import evaluate_ai_demo as evaluation


@pytest.fixture(scope='module')
def evidence():
    value = evaluation.load_reviewed()
    evaluation.reference_facts_valid(value)
    return value


@pytest.mark.parametrize('case', evaluation.CASES, ids=[c[0] for c in evaluation.CASES])
def test_historical_case(evidence, case):
    assert evaluation.evaluate(case, evaluation.record(evidence, case[1], case[2]))['Pass Rate']


@pytest.mark.parametrize('mutation', ['wrong-tool', 'false-cancellation', 'invented-source',
                                     'changed-quote', 'forged-source-path', 'invalid-schema', 'unsupported-answer'])
def test_corrupted_evidence_is_rejected(evidence, mutation):
    case = evaluation.CASES[0 if mutation == 'wrong-tool' else 4 if mutation == 'false-cancellation' else 7]
    entry = evaluation.record(evidence, case[1], case[2])
    if mutation == 'wrong-tool':
        entry['tools_used'] = ['Get_Data_Quality']
    elif mutation == 'false-cancellation':
        entry['answer'] = entry['answer'].replace('Cancellation rows: 41', 'Cancellation rows: 0')
    elif mutation == 'invented-source':
        entry['model_response']['source_ids'] = ['invented-policy']
    elif mutation == 'changed-quote':
        entry['quotes'][0]['text'] += ' synthetic unsupported claim'
    elif mutation == 'forged-source-path':
        for item in entry['retrieved_chunks'] + entry['quotes']:
            item['source_path'] = 'docs/nonexistent-policy.md'
    elif mutation == 'invalid-schema':
        entry['model_response']['answer'] = 'not an array'
    else:
        entry['model_response']['answer'] = ['Missing customer IDs are excluded from sales.']
    assert not evaluation.evaluate(case, entry)['Pass Rate']


def test_historical_no_cancellations_false_positive(evidence):
    entry = evaluation.record(evidence, 'p3_mcp_agent', 38)
    assert entry['status'] == 'PASS'  # Stored execution status alone is insufficient.
    result = evaluation.evaluate(evaluation.CASES[4], entry)
    assert result['Tool Selection Accuracy']
    assert not result['Factual Correctness']
    assert not result['Pass Rate']
