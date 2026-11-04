# Business and system analysis brief

## Purpose and scope

The problem is reliable historical retail reporting: calculate consistent KPIs,
explain their evidence and ensure that only the report reviewed by the owner is
published. The implemented local portfolio joins deterministic SQL reporting,
human approval and separate AI/MCP/RAG analysis demonstrations.

F1-F6 are complete for the bounded portfolio. The [requirements matrix](REQUIREMENTS_MATRIX.md)
records the broader delivered, partial and unverified scope; the
[acceptance criteria](../ACCEPTANCE.md) retain the original gates without claiming
that every deployment, recovery or measurement condition passed.

## Business context and assumptions

The historical retailer is a dataset subject, not a client. No stakeholder
interviews or internal retailer procedures were supplied. The owner plays the
analyst and reviewer roles in an isolated local scenario; this is not evidence of
production segregation of duties, customer adoption or professional client work.

| Role | Documented need | Evidence boundary |
| --- | --- | --- |
| Analyst, represented by the owner | Consistent figures and traceable exceptions | Historical transaction analysis; no observed retailer reporting process |
| Reviewer, represented by the owner | Understand and approve/reject the exact report | Real local owner decisions; automated checks do not replace human approval |
| Operator/developer | Diagnose failures and prevent duplicate publication | Existing guards and durable state; full fresh-machine recovery remains unverified |
| Portfolio reviewer | Assess analysis, architecture and implementation | Public documentation, video, screenshots and bounded execution evidence; installation is optional |

The owner controls project scope, business-rule decisions and acceptance.
Implementation, documentation and automated checks were developed with AI/Codex
assistance; no independently authored codebase or invented personal work history
is claimed.

## AS-IS: illustrative manual baseline

The modeled baseline is a manual exercise over a fixed archive and period:
load records, check validity/completeness, classify adjustments, calculate KPIs,
inspect exceptions, prepare a summary, review it and save the report.

This sequence is an explicit scenario assumption, not an observed retailer
process. The [manual baseline protocol](WP1_MANUAL_BASELINE.md) defines comparable
cases, but no owner timing, active effort, elapsed duration or business savings
has been measured. [Measurement methodology](MEASUREMENT.md) remains a protocol,
not an ROI result.

## TO-BE: implemented local flow and design boundaries

1. The F2 interface submits an owner-authorized creation request through FastAPI.
   HMAC verification and a durable PostgreSQL admission ledger guard the n8n entry.
2. n8n invokes the existing report core; FastAPI/SQL calculates deterministic facts
   and stores the report and an exact approval request. Creation does not approve.
3. The authenticated owner reviews the report, version, hashes, target and deadline,
   then approves or rejects the specific request.
4. Approval can lead to guarded local publication through the existing outbox and
   delivery flow. Rejection stores the decision without a publication intent,
   publication record or receipt. A shared decision workflow may still run.

The [workflow inventory](../workflows/README.md) and
[accepted outcomes](../README.md#verified-tests-and-evidence) describe the delivered
path. F3-F5 separately display verified historical tool calls, MCP results and
RAG answers; they do not silently add LLM commentary to the approved P1 report.
Generalized fault recovery and every original fallback/timeout scenario are not
claimed as accepted merely because they appear in a process model.

## Process models

- [AS-IS BPMN source](WP1_AS_IS.bpmn): illustrative owner-run manual exercise.
- [TO-BE BPMN source](WP1_TO_BE.bpmn): reporting/review/publication design.
- [Model notes and structural-validation limits](WP1_PROCESS_MODELS.md).

The models predate the final F2 interface and include design assumptions such as
a model timeout and fallback routes. They are not a claim that every depicted
branch was executed or formally validated against the complete BPMN schema.
Reliable SVG/PNG previews are not provided: no suitable installed BPMN renderer
was found in the checked project/PATH locations. No approximate replacement was
generated, and the original BPMN files remain unchanged. The
[Mermaid architecture](../README.md#architecture-and-stack) is a system overview,
not a substitute for a BPMN rendering or conformance check.

## Documented scenario decisions

| Topic | Decision or observation | Public reference |
| --- | --- | --- |
| Report purpose | Bounded historical sales and data-quality analysis; figures are recorded-sales proxies, not audited revenue or profit | [KPI definitions](KPI_DICTIONARY.md) |
| Period and cadence | F2 uses the existing fixed historical window; the API supports bounded explicit periods. A general scheduled-report product is not claimed | [API guide](API_DEMO_GUIDE.md), [workflow inventory](../workflows/README.md) |
| Data treatment | Preserve source-row identity; keep otherwise valid sales with missing CustomerID; distinguish cancellations from invalid data-quality rows | [Pinned data contract](DATA_CONTRACT.md), [current-status clarification](DEMO_AND_GITHUB.md#pinned-policy-documents-and-current-status) |
| Review authority | Owner authentication and exact report/version/hash/target/expiry binding; the agent has no approval authority | [Acceptance](../ACCEPTANCE.md), [F2 implementation](../api/f2_creation.py) |
| Publication | Only the isolated local target is demonstrated; creation never implies approval or delivery | [Accepted scope](../README.md#verified-tests-and-evidence) |
| Duplicate or uncertain creation | Durable operation/nonce uniqueness; ambiguous results require reconciliation before any redispatch | [Admission schema](../db/demo/f2_creation.sql), [adapter](../api/f2_creation.py) |
| AI output | Bounded read-only tools and schema/evidence checks; invalid output cannot authorize a decision or publication | [Evaluation report](AI_EVALUATION_REPORT.md) |
| Business effect and cost | No observed time savings, ROI or retailer adoption; local inference has no mandatory paid API, but hardware/effort are not treated as free measured costs | [Measurement protocol](MEASUREMENT.md) |

The KPI dictionary and data contract remain byte-pinned historical RAG sources.
Their [public clarification](DEMO_AND_GITHUB.md#pinned-policy-documents-and-current-status)
separates earlier status prose from the completed system without rewriting evidence.

## User stories and acceptance traceability

Stories state user needs; the delivery column limits what is actually established.
Original AC/AX references point to definitions, not blanket acceptance of all gates.

| ID | Story | Original acceptance | Delivery boundary |
| --- | --- | --- | --- |
| US-01 | As an analyst, I need reproducible reports for a known snapshot and period | AC-02, AC-04, AC-06 | Deterministic local reporting exists; full temporal document/outcome replay is not verified |
| US-02 | As an analyst, I need the source and policy evidence behind a figure | AC-05, AC-22 | SQL provenance, hashes and bounded tool/RAG evidence are available |
| US-03 | As a reviewer, I need to approve or reject the exact report version | AC-11 through AC-15 | Owner-controlled local Approve/PUBLISHED and Reject/REJECTED accepted |
| US-04 | As an operator, I need to resolve failures without duplicate publication | AC-16 through AC-23 | Durable guards and operator reconciliation exist; broad crash/fresh-machine recovery remains partial |
| US-05 | As an evaluator, I need a fair manual/deterministic/AI comparison | AC-25 | Protocol exists; measured effort and savings remain unverified |
| US-06 | As a portfolio reviewer, I need understandable architecture and evidence | AC-24, AC-26, AX-07 | Public media/source are available; clean-instance import and bootstrap remain unverified |

## Priorities and remaining work

Delivered priorities are trusted calculations, explicit evidence, human-controlled
publication and bounded AI/MCP/RAG demonstrations. Remaining unverified work
includes fresh-machine deployment/recovery, Postman GUI execution, AS-IS timing,
paired business-effect measurement and broader evaluation. External business
connectors, OAuth and heavier infrastructure remain deferred.

The portfolio demonstrates implementation and verification within these limits.
No measured effect, stakeholder quotation or professional experience is inferred
from the presence of an artifact. Further work requires a separately agreed scope.
