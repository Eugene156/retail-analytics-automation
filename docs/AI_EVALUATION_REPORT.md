# AI demo evaluation report

Offline replay date: 2026-10-11. The results below preserve that historical replay.
Subsequent P6-A live validation completed eight scenarios across initial and repaired
runs; see [initial evidence](../evidence/p6_live_validation.json) and
[completed Combined checks](../evidence/p6_combined_repair.json). Original execution
IDs and result rows below are unchanged. No new workflow was run for this update.

## Cases and actual replay results

| Case | Historical core execution | Tools | Facts | Citations | Schema | Case |
| --- | --- | --- | --- | --- | --- | --- |
| P2-KPI | 28 | PASS | PASS | N/A | N/A | PASS |
| P2-Quality | 24 | PASS | PASS | N/A | N/A | PASS |
| P2-Combined | 26 | PASS | PASS | N/A | N/A | PASS |
| P3-KPI | 32 | PASS | PASS | N/A | N/A | PASS |
| P3-Combined | 41 | PASS | PASS | N/A | PASS | PASS |
| P4-KPI | 80 | N/A | PASS | PASS | PASS | PASS |
| P4-Cancellations | 82 | N/A | PASS | PASS | PASS | PASS |
| P4-Combined | 84 | N/A | PASS | PASS | PASS | PASS |

## Metrics and denominators

- Tool Selection Accuracy: 5/5 (100.0%).
- Factual Correctness: 8/8 (100.0%).
- Citation Validity: 3/3 (100.0%).
- Schema Compliance: 4/4 (100.0%).
- Pass Rate: 8/8 (100.0%).

## Method and evidence

Publication preflight checks the three existing evidence JSON files and MCP
discovery against known local secrets/provider patterns before reading results.
No raw execution export or new private log is generated. Inputs:
[P2](../evidence/p2_ai_agent.json), [P3](../evidence/p3_mcp_agent.json),
[P4](../evidence/p4_rag_runtime.json), [MCP facts](../evidence/p3_mcp_discovery.json).

| Case | Frozen expectation |
| --- | --- |
| P2-KPI | KPI only; net79.42, sales1349.45, sale rows33 |
| P2-Quality | Data Quality only; zero findings |
| P2-Combined | Both tools; net79.42, sales1349.45, cancellations41/1270.03; zero findings |
| P3-KPI | MCP KPI only; net79.42, sales1349.45, sale rows33 |
| P3-Combined | Both MCP tools; all seven labelled facts match responses |
| P4-KPI | Net sales formula and adjustment exclusion; kpi-dictionary |
| P4-Cancellations | Cancellation versus invalid rows; no inferred return/refund; both sources |
| P4-Combined | Net/adjustments, missing IDs retained, row coverage; both sources |

Tool Selection Accuracy is exact expected-set agreement per applicable case.
P2 uses saved tools_used summaries (not independent reinspection of tool calls);
P3 additionally checks MCP response bodies and agent intermediate tool actions.
P4 retrieves before the agent, so tool selection is N/A.

Factual Correctness means bounded required-fact compliance, not all-prose accuracy.
P2 and historical P3 single-tool answers check required numeric tokens/zero-quality
phrases against fixed-period SQL/MCP reference values. These limited checks cannot
prove number-to-label binding or catch every additional unsupported claim. Current
P3 combined output uses exact labels/Decimal comparison against actual MCP bodies.
P4 reuses existing ANSWER_RULES and required-topic anchors in actual retrieved
chunks; model sentences must be unchanged and match the bounded policy vocabulary.

Citation Validity requires actual retrieved source/chunk membership, exact quote
text/path, matching source_ids and execution URL. Retrieved text/path/hash must
also match the existing policy corpus rebuilt from source documents; only P4
has applicable citations.
Schema Compliance checks P4 model JSON shape and P3 combined label contract.
P2 and older P3 single-tool JSON schema proof is unavailable: N/A, not PASS.
Pass Rate requires every applicable metric; N/A never contributes to denominators.

Historical P3 execution38 says "No cancellations" despite41 cancellations.
It is retained as a rejection regression, not silently relabelled by its stored
PASS status. The final repair execution41 is the combined acceptance case.

## Offline and live separation

Run `python scripts/evaluate_ai_demo.py` to replay; add `--report` to regenerate
this report. CI runs only offline pytest checks of replay and corrupted cases.
Existing G0 evaluator design (fixed cases, explicit failures and denominators)
is reused conceptually; it is not invoked because it performs live inference.

The following was the 11 October live-validation plan, subsequently exercised in
the P6 evidence linked above. Any further live run requires new owner authorization.
For an authorized future evaluation, manually run
P2 KPI/quality/combined, P3 single/combined (including41 and GBP1270.03), and
P4 KPI/cancellations/combined, one at a time. Use the eight case expectations
in CASES, preserve failed runs, record model/workflow versions and elapsed time,
then apply existing check_p2_demo/check_p3_demo/check_p4_demo safety checks only
after reviewing their operations and obtaining required Docker permissions.
No live executor is installed in CI; this offline command never launches one.

Manual parents: [P2](http://127.0.0.1:15690/workflow/p2-read-agent-demo-v1),
[P3](http://127.0.0.1:15690/workflow/p3-mcp-agent-demo-v1),
[P4](http://127.0.0.1:15690/workflow/p4-rag-demo-v1). After authorization, edit
the Question node and Execute workflow; do not execute guarded cores directly.
Use saved P2/P4 questions from the selected evidence entries. For P3 ask
"What are the sales KPIs for the demo period?" then "Summarize sales KPIs,
cancellations and data quality for the demo period." Fresh P3 single-tool output
must satisfy the current five KPI labels, beyond the older execution32 checks.

## Limitations

Eight selected historical development demonstrations, not held-out cases or a
statistical benchmark. Model/prompt versions differ between old P3 single and
repaired combined cases. Saved summaries do not prove current runtime behavior.
P4 has a finite policy corpus; live abstention, hostile input, nondeterministic
reruns and broad retrieval recall/precision are not evaluated here. Localhost
citation URLs identify historical runs and are not public clickable evidence.
A 100% replay result is not a claim of general model accuracy or production readiness.
