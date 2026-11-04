# Acceptance criteria

## Published portfolio acceptance (4 November 2026)

F1-F6 are complete. P1/F2 report creation, owner Approve-to-PUBLISHED and separate
Reject-to-REJECTED were accepted in the isolated local environment. Rejection may
execute the shared decision workflow, but must create no publication intent,
record or receipt. AI/MCP/RAG results shown in F3-F5 are historical evidence.

The original AC/AX criteria below are retained as acceptance definitions, not a
claim that every original gate passed. Fresh-machine bootstrap, broad held-out
measurement and optional external connectors remain unverified or deferred.
See the [current requirement statuses](docs/REQUIREMENTS_MATRIX.md),
[delivered scope](README.md#six-implemented-website-sections),
[P1 evidence](evidence/p12_human_approval.json),
[initial AI checks](evidence/p6_live_validation.json) and
[completed Combined checks](evidence/p6_combined_repair.json).
The initial AI receipt preserves failures; it must be read with the later receipt.
Historical release verification recorded 56 local pytest passes and a successful
hosted run. See the [CI workflow history](https://github.com/Eugene156/retail-analytics-automation/actions/workflows/ci.yml)
for subsequent commit results; no new tests were run for this documentation update.

## Acceptance status: public evidence and gaps

**AC** identifies an original core acceptance criterion; **AX** identifies an
original extension criterion. These IDs refer to the complete conditions retained
below, not just the portfolio feature with a similar name.

- **VERIFIED:** public evidence supports the entire criterion for its stated path.
- **PARTIAL:** bounded subconditions have implementation/evidence, with a remaining gap.
- **UNVERIFIED:** the original outcome is not established by available public evidence.
- **DEFERRED:** explicitly outside the completed project scope.

A DELIVERED requirement is not automatically a VERIFIED AC/AX criterion. Source
and test definitions establish design/coverage intent, not an unrecorded live run.
Private or unavailable historical evidence is not promoted to a public pass.
The accepted local Human Approval demonstration remains accepted; broader original
criterion gaps below do not revoke that bounded result. No new tests were run.

| Criterion | Status | Public evidence / explicit remaining gap |
| --- | --- | --- |
| AC-01 | UNVERIFIED | [Setup limits](docs/DEMO_AND_GITHUB.md#workflow-portability-and-setup): the existing local environment works; a fresh supported-machine bootstrap has not been verified. |
| AC-02 | PARTIAL | [Source profile](docs/G0_DATA_PROFILE.md) and [SQL notes](docs/WP2_CANONICAL_KPIS.md) record measured workbook/import totals. A complete public accepted/flagged/quarantined import reconciliation is not supplied. |
| AC-03 | UNVERIFIED | [Source identity policy](docs/DEMO_AND_GITHUB.md#pinned-policy-documents-and-current-status) is documented; no public receipt establishes the specified ten deliveries and preserved identical-valued rows together. |
| AC-04 | PARTIAL | [Golden cases](docs/WP1_GOLDEN_CASES.md) and [SQL notes](docs/WP2_CANONICAL_KPIS.md) cover bounded classification/period cases; the complete listed edge-case set with delivered exclusion counts is not publicly demonstrated. |
| AC-05 | PARTIAL | [Canonical SQL notes](docs/WP2_CANONICAL_KPIS.md) record bounded exact checks and explicitly do not claim an AC-05 release pass. Broader workbook reconciliation evidence is private, not a new public full-criterion result. |
| AC-06 | PARTIAL | [Canonical SQL notes](docs/WP2_CANONICAL_KPIS.md) support invoice-time boundaries. Full earlier-case exclusion of later document revisions and outcome labels remains unverified; see [scope clarification](docs/DEMO_AND_GITHUB.md#pinned-policy-documents-and-current-status). |
| AC-07 | VERIFIED | [P1 report core](workflows/p12_report_core.json) contains no LLM step; [P1.2 review/decision evidence](evidence/p12_human_approval.json) records actual review outcomes. The [review renderer](api/portal_review_v3.py) explicitly labels the stored deterministic report. This verifies the P1 no-AI report path, not a general agent-fallback scenario. |
| AC-08 | PARTIAL | [AI report](docs/AI_EVALUATION_REPORT.md) and [live evidence](evidence/p6_combined_repair.json) establish bounded local responses. The specified ten-case commentary trial with pre-agreed thresholds, abstentions and latency is not fully established by the public set. |
| AC-09 | PARTIAL | [Evaluation regressions](tests/test_ai_evaluation.py) and [report](docs/AI_EVALUATION_REPORT.md) cover malformed/unsupported evidence. A complete repair-once-to-manual-review integration result is not publicly demonstrated. |
| AC-10 | PARTIAL | [P1 report core](workflows/p12_report_core.json) is model-independent and [P2 core](workflows/p2_read_agent_core.json) has safe-failure handling. The complete model-unavailable/timeout report-fallback scenario is not verified as one public acceptance case. |
| AC-11 | PARTIAL | [P1.2 evidence](evidence/p12_human_approval.json) records APPROVED with one publication; [current acceptance summary](README.md#verified-tests-and-evidence) records owner acceptance. The public summary does not expose every exact-bound queuing/audit assertion required by this full criterion. |
| AC-12 | PARTIAL | [P1.2 evidence](evidence/p12_human_approval.json) records REJECTED with zero publications. Rejection is accepted locally, but the full expiry branch has no equivalent public result. A shared decision-workflow execution is allowed; publication is not. |
| AC-13 | PARTIAL | [Review implementation](api/portal_review_v3.py) enforces exact request/report bindings. Public evidence does not establish every changed-payload, changed-target and changed-revision end-to-end denial. |
| AC-14 | PARTIAL | [Decision/outbox foundation](db/migrations/019_decision_outbox_foundation.sql) implements durable decision/action constraints. The exact simultaneous-or-ten-repeated-approval callback acceptance result is not publicly recorded; creation idempotency is a different test. |
| AC-15 | PARTIAL | [F2 security tests](tests/test_f2_creation.py) and [portal guards](api/portal.py) cover bounded denial conditions. A complete public live record of all listed actors/signatures and permitted audit-only mutations is unavailable. |
| AC-16 | PARTIAL | [P1 report core](workflows/p12_report_core.json) contains bounded backoff and operator recovery. Retry-After handling plus the specified 429/503-to-dead-letter outcomes are not fully established by public evidence. |
| AC-17 | PARTIAL | [P1 report core](workflows/p12_report_core.json) distinguishes retry and stop paths. Public receipts do not explicitly demonstrate the complete permanent-validation/authentication-4xx scenario and operator-visible outcome. |
| AC-18 | PARTIAL | [Decision/outbox schema](db/migrations/019_decision_outbox_foundation.sql) and [local approval evidence](evidence/p12_human_approval.json) support durable bounded delivery. The prescribed before/after-dispatch crash recovery suite is not public evidence here. |
| AC-19 | PARTIAL | [F2 adapter](api/f2_creation.py) and [tests](tests/test_f2_creation.py) model uncertain creation outcomes without automatic redispatch. They do not establish the entire external-write connector-test-double publication scenario. |
| AC-20 | PARTIAL | [F2 adapter](api/f2_creation.py) provides operator reconciliation and [tool-fact receipt](evidence/p6_combined_repair.json) preserves earlier AI failures. These do not prove the entire repaired-business-case replay criterion. |
| AC-21 | UNVERIFIED | [Security boundaries](docs/TECHNOLOGY_ROADMAP.md#architecture-and-engineering-boundaries) constrain tool authority; the prescribed five hostile-text privacy/misuse acceptance outcomes are not publicly established. |
| AC-22 | PARTIAL | [HTTP correlation evidence](evidence/p6_live_validation.json) and [logging implementation](api/observability.py) establish bounded request/log correlation. A complete case/execution/action trace and universal absence of secrets in all logs are not proved. |
| AC-23 | UNVERIFIED | [Recovery limits](README.md#known-limitations-and-release-boundaries): no public restore receipt establishes all specified counts, case, approval and audit preservation. Private backup verification is not being denied or represented as a public/fresh-machine result. |
| AC-24 | PARTIAL | [Workflow inventory](workflows/README.md) provides sanitized definitions used in the existing environment. Clean-instance import/rebinding acceptance remains unverified. |
| AC-25 | UNVERIFIED | [Manual baseline](docs/WP1_MANUAL_BASELINE.md) and [measurement protocol](docs/MEASUREMENT.md) define cases; the ten paired manual/deterministic/AI timing and quality observations have not been collected. |
| AC-26 | PARTIAL | [Published artifacts](README.md) include source attribution, architecture, tests and media. [BPMN notes](docs/WP1_PROCESS_MODELS.md) retain modeling/validation limits; this is not full original-specification acceptance. |
| AX-01 | DEFERRED | [Scope boundaries](docs/TECHNOLOGY_ROADMAP.md#implemented-stack-4-november-2026): an approval-gated GitHub task connector is outside the delivered scope. Publishing this repository is not that product action. |
| AX-02 | DEFERRED | [Technology scope](docs/TECHNOLOGY_ROADMAP.md#implemented-stack-4-november-2026): Telegram notification/approval was not included in the completed portfolio. |
| AX-03 | DEFERRED | [Requirement boundaries](docs/REQUIREMENTS_MATRIX.md) distinguish existing owner/service authentication from the out-of-scope OAuth authorization/revocation/reconnect increment. |
| AX-04 | PARTIAL | [Agent evidence](evidence/p6_combined_repair.json) and [P2 core](workflows/p2_read_agent_core.json) show real multi-tool choice and bounded validation. General state recovery and the complete unauthorized-tool acceptance set remain unverified. |
| AX-05 | PARTIAL | [P4 RAG evidence](evidence/p4_rag_runtime.json) establishes embeddings, retrieval and citations. Update/delete behavior, broader retrieval quality and full-context/search baseline comparisons remain unverified. |
| AX-06 | PARTIAL | [MCP discovery](evidence/p3_mcp_discovery.json) and [agent calls](evidence/p6_combined_repair.json) establish the own-server integration. A meaningful external server and all prescribed auth/timeout compatibility cases are not established. |
| AX-07 | DEFERRED | [Portability scope](docs/DEMO_AND_GITHUB.md#workflow-portability-and-setup) explicitly defers the reduced clean-instance/importable demonstration. Existing exports do not prove that minimal-setup outcome. |
| AX-08 | DEFERRED | [Technology scope](docs/TECHNOLOGY_ROADMAP.md#implemented-stack-4-november-2026) excludes the Metabase/dbt/Pandera/DuckDB BI extension from delivered capabilities. |
| AX-09 | PARTIAL | [Evaluation report](docs/AI_EVALUATION_REPORT.md) documents a bounded retrospective set. Larger held-out evaluation, uncertainty experiments and quality-adjusted effort measurement remain unverified. |
| AX-10 | DEFERRED | [Technology scope](docs/TECHNOLOGY_ROADMAP.md#implemented-stack-4-november-2026) excludes the alert/recovery monitoring increment. Health checks do not count as an observed alert and recovery. |

Obsolete checkpoint details remain in
[Git history](https://github.com/Eugene156/retail-analytics-automation/commits/main/ACCEPTANCE.md).
Historical test totals are tied to their original environment/scope and are not
new verification of the full criteria below.

## v0.1 release gates

| ID | Given / When | Then |
| --- | --- | --- |
| AC-01 | A fresh supported machine has documented prerequisites; bootstrap is followed | The pinned core becomes healthy; steps, downloads, resource usage and any manual setup are recorded |
| AC-02 | A complete verified archive is imported | File hash, sheets and all physical rows are accounted for as accepted, flagged or quarantined; counts are measured, not copied from a website |
| AC-03 | The same archive/import event is delivered ten times | No duplicate source-row identity is inserted; valid identical-valued source rows remain present |
| AC-04 | Missing IDs/descriptions, cancellations, negative/zero values and invalid dates occur | The data contract is applied and the report exposes its inclusion/exclusion counts |
| AC-05 | Hand-checked monetary fixtures are aggregated | SQL totals and denominators match exact expected values; no binary-float monetary drift |
| AC-06 | A report interval ends at a defined cutoff | No later invoice, document revision or outcome enters the calculation or AI evidence |
| AC-07 | AI is disabled | A complete deterministic report reaches review with no model call and is clearly labelled |
| AC-08 | A local model is available and receives ten bounded pilot cases | Actual responses, schema validity, evidence checks, abstentions and latency are recorded; passing quality thresholds are defined before evaluation |
| AC-09 | The model returns malformed JSON, an unknown evidence ID or a wrong number | Output is rejected; at most one repair call occurs; unresolved failure reaches labelled manual review |
| AC-10 | The model service is unavailable or exceeds its timeout | No uncontrolled retries; the deterministic report remains available and no AI success is recorded |
| AC-11 | An authorized reviewer approves the current unexpired proposal | Only the exact approved payload/target is queued and a decision audit event is written |
| AC-12 | A reviewer rejects or the approval expires | No corresponding business action is executed; the outcome is visible |
| AC-13 | Payload, destination or report revision changes after approval | The old approval is invalid and a new decision is required |
| AC-14 | Two simultaneous or ten repeated approval requests arrive | A single logical decision/action survives under database constraints; replays do not execute again |
| AC-15 | A wrong user, modified token or invalid webhook signature is submitted | The request is denied; no case/action mutation occurs beyond a safe security audit |
| AC-16 | A retryable endpoint returns 429 or 503 | Bounded backoff is used, Retry-After is respected when valid, and retry exhaustion reaches dead-letter |
| AC-17 | A permanent validation/authentication 4xx occurs | It is not retried indefinitely; the operator sees a useful safe error |
| AC-18 | The process crashes before/after outbox dispatch | Durable state is recovered; local publication remains single-effect for the same action key |
| AC-19 | An external write times out with an unknown outcome (connector test double) | State is `unknown`; reconciliation precedes any retry; ambiguous results require intervention |
| AC-20 | A failed case is repaired and replayed by an authorized operator | Business identity is preserved, a new execution is audited, and prior evidence remains accessible |
| AC-21 | Five hostile product/document texts request secret disclosure or tool misuse | They cannot modify permissions, write externally, or cause secret output; the limited nature of the smoke test is documented |
| AC-22 | A report completes or fails | Case/execution/action IDs connect workflow, API, database and audit records; logs contain no secrets |
| AC-23 | Backup is restored into a separate test database | Known counts, a case, its approval and audit survive; operational volumes are not deleted to hide failure |
| AC-24 | Workflows are exported then imported into a clean local n8n instance | Sub-workflow links and credential binding instructions work for the pinned version; no private credentials are embedded |
| AC-25 | Ten representative reporting cases are exercised manually, without AI, and with AI | Active minutes, elapsed time, assistance, quality and failures are separately recorded; no invented savings |
| AC-26 | Release artifacts are inspected | English README, source attribution, BPMN files, architecture, tests, status and demo are consistent with what actually ran |

For AC-08, agree a small task-specific acceptance threshold during G0 and before using held-out cases. JSON validity alone is insufficient: no contradictory or unsupported claim may pass the deterministic publication checks. Abstention/manual review remains a valid failure-handling outcome, but does not count as successful AI analysis.

## Connected v0.1+ / v0.2 gates

| ID | Scenario | Required evidence |
| --- | --- | --- |
| AX-01 | Real GitHub task action in an owner-controlled demo repository | Fresh auth, exact target allowlist, approval, external URL, uncertain-outcome reconciliation, no duplicate action |
| AX-02 | Real Telegram notification/approval | Own bot/chat, authenticated allowlisted reviewer, callback replay/expiry tests; one polling consumer or a valid HTTPS webhook |
| AX-03 | OAuth 2.0 connection | Authorization, callback/state validation, permission scope, revocation and reconnect; not merely a pasted token |
| AX-04 | Native n8n agent with several tools | Real model-driven tool choice, typed arguments, step limit, state recovery and denied unauthorized tool calls |
| AX-05 | Local pgvector RAG | Real source provenance, retrieval quality, source references, update/delete behavior and comparison against simple full-context/search baselines |
| AX-06 | MCP integrations | n8n reaches our service and one meaningful external server, lists/calls actual tools, tests auth/timeout and records actual protocol compatibility |
| AX-07 | Importable demonstration JSON | Imports from the GitHub raw URL into a clean supported n8n; runs with minimal documented setup and clearly marks reduced capability |
| AX-08 | BI and analytics extension | Metabase dashboard values match SQL; dbt/Pandera/DuckDB duties are distinct and test evidence is reproducible |
| AX-09 | Larger evaluation and measurement | Frozen held-out cases, appropriate uncertainty reporting, quality-adjusted time comparison and honest resume statement |
| AX-10 | Monitoring and recovery | One observed alert and its recovery path; queue restart tests only if the queue profile is actually enabled |

## Laboratory admission

Each lab needs a concrete question, a fixed baseline, a resource/time budget, a runnable example, and a result. Documentation-only comparison is not implementation experience. Failed or no-benefit experiments are legitimate evidence when reported accurately.

## Human acceptance

The owner checks the report against source records, performs the manual timing protocol, and explains the workflow and major SQL rules aloud. AI can prepare drafts and scripts, but cannot fabricate stakeholder interviews, personal execution times, acceptance signatures or a demo recording.

## Release decision

All applicable gates need an observed result and evidence. A blocked gate remains blocked. A reduced release can be published with explicit scope/limitations, but must not be labelled as passing the full specification. Do not silently replace missing external integration evidence with mocked responses.
