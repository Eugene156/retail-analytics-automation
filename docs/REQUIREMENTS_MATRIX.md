# Requirements traceability

## Current delivery status (4 November 2026)

P1-P5 and F1-F6 are complete for the bounded local portfolio, with public source,
media, real Human Approval acceptance and local/hosted CI. The original R01-R43
scope below also included broader deployment, evaluation and connector goals;
completion of the portfolio does not turn those into delivered features.

- **DELIVERED:** the named bounded capability has implementation or recorded evidence.
- **PARTIAL:** some requested scope is present; the missing part is named explicitly.
- **DEFERRED:** outside the delivered scope; no implementation claimed.
- **UNVERIFIED:** an outcome is not established by available evidence.

A source link establishes implementation, not an independent live-test result.
Dated receipts establish their recorded environment/time only. F2 owner acceptance
is summarized in README; raw current database/session evidence remains private.
[Original acceptance IDs](../ACCEPTANCE.md) are retained for traceability, not a
blanket statement that all their subconditions passed. See also
[workflow inventory](../workflows/README.md) and [evaluation report](AI_EVALUATION_REPORT.md).

| ID | Requirement | Status | Original acceptance | Public reference | Verified scope / remaining limitation |
| --- | --- | --- | --- | --- | --- |
| R01 | Business problem | DELIVERED | AC-25, AC-26 | [Business analysis](BUSINESS_ANALYSIS.md) | Illustrative business problem and stakeholder roles; no retailer interviews or measured savings claimed. |
| R02 | Real data | DELIVERED | AC-02 | [Source-data profile](G0_DATA_PROFILE.md) | Complete pinned historical workbook profiled; raw rows remain private. |
| R03 | AS-IS | PARTIAL | AC-25, AC-26 | [Manual baseline protocol](WP1_MANUAL_BASELINE.md) | AS-IS model and protocol exist; owner timing and observed retailer operations are unverified. |
| R04 | TO-BE | DELIVERED | AC-11 through AC-20 | [Workflow inventory](../workflows/README.md) | Local deterministic reporting, explicit review and guarded publication work; broader proposed recovery remains bounded. |
| R05 | BPMN 2.0 | PARTIAL | AC-26 | [BPMN model notes](WP1_PROCESS_MODELS.md) | AS-IS/TO-BE BPMN and structural checks exist; formal conformance and final F2 process reconciliation are not established. |
| R06 | Functional/non-functional requirements | DELIVERED | AC-26 | [Original specification](../SPEC.md) | Functional/nonfunctional definitions are retained; this does not mark all original gates passed. |
| R07 | User stories | DELIVERED | AC-26 | [User stories](BUSINESS_ANALYSIS.md#user-stories) | Stories name roles and original acceptance IDs; business assumptions remain explicit. |
| R08 | Acceptance criteria | PARTIAL | AC-01 through AC-26 | [Acceptance criteria](../ACCEPTANCE.md) | Criteria preserved and local acceptance recorded; full original fresh-machine/measurement gates are not met. |
| R09 | n8n | DELIVERED | AC-24 | [Workflow inventory](../workflows/README.md) | Working native n8n orchestration and sanitized exports; fresh-instance import is separate and unverified. |
| R10 | Multi-step workflows | PARTIAL | AC-24 | [P1 report core](../workflows/p12_report_core.json) | Branches, bounded retries and reusable workflows exist; every planned scheduling/batching/wait family is not demonstrated. |
| R11 | Reusable sub-workflows | PARTIAL | AC-24 | [Workflow inventory](../workflows/README.md) | Parent/core calls verified locally; clean-instance credential/sub-workflow rebinding is unverified. |
| R12 | Real REST APIs | PARTIAL | AC-15, AX-01, AX-02 | [REST API guide](API_DEMO_GUIDE.md) | Real local FastAPI contracts verified; external business REST connectors are deferred. Git publishing is tooling, not a product connector. |
| R13 | Webhooks | DELIVERED | AC-03, AC-15 | [F2 creation adapter](../api/f2_creation.py) | HMAC-signed creation gate and durable nonce/operation admission exist; source and focused tests support the bounded integration. |
| R14 | OAuth / API authentication | PARTIAL | AC-15, AX-03 | [Owner portal guards](../api/portal.py) | Owner sessions, CSRF and service authentication exist; OAuth authorization/revocation/reconnect is deferred. |
| R15 | JSON processing | DELIVERED | AC-04, AC-09 | [Public OpenAPI schema](openapi_demo.json) | Typed JSON request validation and deterministic workflow output contracts. |
| R16 | PostgreSQL | DELIVERED | AC-18, AC-23 | [F2 admission schema](../db/demo/f2_creation.sql) | PostgreSQL owns facts, cases and durable admission/state constraints; fresh-machine restore remains separate. |
| R17 | SQL | DELIVERED | AC-05 | [Canonical KPI SQL](../db/migrations/008_canonical_period_kpis_v1.sql) | Deterministic canonical KPI SQL; arithmetic and provenance documented in the public contracts. |
| R18 | LLM API | DELIVERED | AC-08, AC-10 | [P2 execution evidence](../evidence/p2_ai_agent.json) | Real local Ollama inference recorded; no mandatory hosted provider. |
| R19 | Structured outputs | DELIVERED | AC-09 | [AI evaluation report](AI_EVALUATION_REPORT.md) | Structured response/source checks and corrupted-evidence regression cases; no general correctness guarantee. |
| R20 | Model-driven tool calling | DELIVERED | AX-04 | [Combined tool-fact evidence](../evidence/p6_combined_repair.json) | Native agent selects actual read-only tools; original model JSON and fact provenance retained. |
| R21 | AI agent | PARTIAL | AX-04 | [AI Agent core](../workflows/p2_read_agent_core.json) | Native bounded AI Agent exists; generalized persistent agent-state recovery is not demonstrated. |
| R22 | Several agent tools | DELIVERED | AX-04 | [AI Agent core](../workflows/p2_read_agent_core.json) | Two real read-only tools: Sales KPIs and Data Quality. RAG retrieval is a separate pre-agent step. |
| R23 | RAG | PARTIAL | AX-05 | [RAG execution evidence](../evidence/p4_rag_runtime.json) | Real retrieval/context/citations verified; update/delete, broad relevance and baseline comparisons remain unverified. |
| R24 | Vector database | DELIVERED | AX-05 | [pgvector schema](../demo/p4_schema.sql) | pgvector stores embeddings and supports similarity search; alternative-store comparison is deferred. |
| R25 | MCP | PARTIAL | AX-06 | [MCP discovery evidence](../evidence/p3_mcp_discovery.json) | Own MCP server discovery/calls and n8n client work; meaningful external MCP integration is deferred. |
| R26 | Python and JavaScript | DELIVERED | AC-04, AC-24 | [Workflow inventory](../workflows/README.md) | Python FastAPI, JavaScript workflow validation and vanilla browser UI implemented. |
| R27 | Error handling | PARTIAL | AC-16 through AC-20 | [P1 report core](../workflows/p12_report_core.json) | Safe failures/operator recovery and guarded publication exist; universal error-workflow/dead-letter coverage is not claimed. |
| R28 | Retries | PARTIAL | AC-16, AC-17 | [P1 report core](../workflows/p12_report_core.json) | Workflow-specific bounded retries exist; uncertain F2 creation is never automatically redispatched. General Retry-After behavior is not proved. |
| R29 | Fallback | PARTIAL | AC-10 | [P1 report core](../workflows/p12_report_core.json) | P1 deterministic report is independent of LLM availability; full integrated commentary-fallback acceptance is not demonstrated. |
| R30 | Logging/audit | PARTIAL | AC-22 | [Structured HTTP logging](../api/observability.py) | JSON HTTP logging and server-generated X-Request-ID verified; no propagated distributed trace. |
| R31 | Monitoring | PARTIAL | AX-10 | [Known limitations](../README.md#known-limitations-and-release-boundaries) | Service health checks exist; an observed alert/recovery monitoring integration is deferred. |
| R32 | Human approval | DELIVERED | AC-11 through AC-15 | [Acceptance and test summary](../README.md#verified-tests-and-evidence) | Real owner Approve/PUBLISHED and separate Reject/REJECTED accepted locally; rejected requests create no publication intent/record/receipt. |
| R33 | Security | PARTIAL | AC-15, AC-21, AC-22 | [F2 creation adapter](../api/f2_creation.py) | Owner/Host/Origin/CSRF, HMAC, idempotency and read-only tool boundaries exist; broad adversarial/prompt-injection assurance is unverified. |
| R34 | Git/GitHub | DELIVERED | AC-26 | [Published repository](https://github.com/Eugene156/retail-analytics-automation) | Public repository, sanitized source and documentation history; no product GitHub task connector implied. |
| R35 | Docker/deployment | PARTIAL | AC-01, AC-23 | [Local demo instructions](../README.md#local-demonstration) | Existing local Docker environment verified; fresh-machine bootstrap/recovery and portable public deployment configuration remain unverified. |
| R36 | Testing/UAT | PARTIAL | AC-01 through AC-26 | [Acceptance and test summary](../README.md#verified-tests-and-evidence) | 56 selected CI tests and local owner/live scenarios passed; original full acceptance matrix is not comprehensively executed. |
| R37 | AI evaluation | PARTIAL | AC-08, AX-09 | [AI evaluation report](AI_EVALUATION_REPORT.md) | Eight-case retrospective offline evaluation and bounded live checks; frozen held-out benchmarks/uncertainty experiments remain unverified. |
| R38 | Documentation | PARTIAL | AC-26 | [Project overview](../README.md) | Public engineering/analysis documentation and media delivered; full public installation/recovery guide is outside the verified scope. |
| R39 | Architecture | PARTIAL | AC-26 | [Architecture overview](../README.md#architecture-and-stack) | Mermaid architecture and BPMN published; complete validated C4/ERD/sequence/state artifact coverage is not claimed. |
| R40 | KPI definitions | DELIVERED | AC-05 | [KPI dictionary](KPI_DICTIONARY.md) | KPI formulas, units, exclusions and denominators defined; source corpus is pinned for historical RAG evidence. |
| R41 | Business impact | UNVERIFIED | AC-25, AX-09 | [Measurement protocol](MEASUREMENT.md) | Measurement protocol only; no observed manual/deterministic/AI paired timings, savings or retailer adoption. |
| R42 | Demonstration | PARTIAL | AC-26, AX-07 | [Published demo guide](DEMO_AND_GITHUB.md) | Six screenshots and optimized video published; local site works. Fresh-instance reduced JSON demo and reviewer bootstrap are unverified. |
| R43 | Employer-facing README | DELIVERED | AC-26 | [Project overview](../README.md) | English README presents problem, bounded capabilities, evidence, media, attribution and limitations. |

No complete requirement is marked DEFERRED because each named requirement has
at least an artifact or a bounded implementation; deferred subfeatures are named
in PARTIAL rows. This is not a claim that those subfeatures work.


## Supporting calculation artifacts

The removed ledger added no unique current delivery status. These public references
remain useful with their original scope:

- [Policy-v1 golden cases](WP1_GOLDEN_CASES.md) and
  [synthetic inputs](../tests/fixtures/kpi_policy_v1.json): fixture consistency,
  not an independent application-SQL or business-impact acceptance result.
- [Canonical SQL verification notes](WP2_CANONICAL_KPIS.md): dated bounded SQL
  results, not a full AC-05/AC-06 release pass.
- [Frozen manual case definitions](../tests/fixtures/wp1_manual_cases_v1.json):
  selected inputs, not observed human timings or measured savings.

The obsolete checkpoint ledger and original planning matrix remain available in
[Git history](https://github.com/Eugene156/retail-analytics-automation/commits/main/docs/REQUIREMENTS_MATRIX.md).
