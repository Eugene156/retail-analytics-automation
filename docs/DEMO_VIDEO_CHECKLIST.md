# Portfolio demo preparation (P6-B)

Prepared 2026-10-11. Recording/screenshots pending. Latest P6-A acceptance: 8/8,
combining six earlier passes with two repaired Combined runs (not eight reruns).
The owner manually confirmed P2#104 and P3#106. Fresh P1 decisions remain pending.

## Four-minute English script

Use saved AI executions, labelled as previously verified runs. Do not click
Execute on P2-P4 during preparation. Only the owner performs fresh P1 decisions.
Edit waiting time if needed, without presenting edited time as execution latency.

| Time | Open and click | Narration |
| --- | --- | --- |
| 0:00-0:20 | README purpose, architecture diagram and stage table | “This is a local retail analytics portfolio showcase. n8n orchestrates processes, PostgreSQL owns the facts, and FastAPI exposes bounded contracts. It is a working demo, not a production deployment.” |
| 0:20-1:15 | Fresh P1 creation, approval page, decision execution and publication receipt; steps below | “A manual n8n run requests a report through FastAPI. SQL calculates the figures. Approval binds this exact report version, hash, reviewer, target and deadline. I approve it myself; only then can the guarded workflow publish to local demo storage.” |
| 1:15-1:40 | Another fresh case: Reject, result page and decision history | “This separate report is rejected. Its decision is stored, but there is no publication or download. The agent never has approval authority.” |
| 1:40-2:15 | P2#104: AI Agent actual tool steps, model JSON and Validate tool evidence | “A native n8n AI Agent uses local Ollama and selects both read-only tools. These are real API responses. The model returns validated tool references; mandatory numeric lines are generated from those responses with field provenance, rather than invented by the model.” |
| 2:15-2:45 | P3#106: MCP Client Tool connection, discovered tools, actual MCP requests/results and validator | “The same capabilities are exposed through a lightweight MCP server. The supported client discovers the tools and the model calls both. Forty-one cancellations, worth twelve hundred seventy pounds and three pence, are business events, distinct from zero quality findings.” |
| 2:45-3:25 | P4#102: Embed question, Semantic search output, agent context, Structured Output Parser and Validate sources | “Policy documents were chunked and embedded locally. pgvector retrieves similar fragments before the agent answers. These are the retrieved source IDs and structured model response. Source IDs and content are checked; exact quotes are generated from the retrieved chunks.” |
| 3:25-4:00 | CI YAML, evaluation report, public API/Postman files, logging receipt; finish on README limits | “Portable CI excludes local services and inference. Evaluation separates offline replay from real live runs. OpenAPI and Postman document safe requests. HTTP completion logs correlate requests without payloads or credentials. Hosted CI and Postman import still need confirmation; automatic deployment and full distributed tracing are not implemented.” |

For embeddings/indexing, show the existing P4 index workflow definition and
reviewed evidence as prior indexing; do not rerun ingestion. For MCP discovery,
show the client configuration and reviewed discovery evidence; do not invent a
separate discovery node. Show original model JSON separately from generated facts.

## Fresh manual P1: Approve, then Reject

These steps change demo state and are for the owner. P6-B created no cases and
made no decisions. Use P1.2; the legacy P1.1 workflow's API token is revoked.

1. Sign in privately to [n8n](http://127.0.0.1:15690) and the
   [portal](http://127.0.0.1:18082/portal) with existing demo-only authority.
   Keep login, token entry and password manager off camera.
2. Open [Create report](http://127.0.0.1:15690/workflow/p12-create-report-v1)
   and click **Execute workflow** once. No code editing: the idempotency key
   includes the execution ID, so each new run creates a fresh case.
3. Wait for **Open Human Approval request**. Note its case_id/request_id and
   open its review_url. Alternatively refresh the portal and select the matching
   request. Do not reuse an expired historical request.
4. Review the report/hash/deadline. Tick **I confirm my selected decision for
   this exact request, report hash, portal target and original deadline**.
   Click **Approve exact portal request**.
5. Expect **PUBLISHED**. Follow **Request, report and publication receipt**;
   show **Committed publication** and **Download exact published JSON**.
   Approval precedes publication; a receipt proves publication, a draft does not.
6. Open [Human Decision history](http://127.0.0.1:15690/workflow/p12-human-decision-v1/executions).
   Choose the new execution matching request_id; show **Publish only approved
   report** and **Human Approval result**. Note the new execution ID.
7. Repeat steps 2-3 for a **different case**. Tick confirmation and click
   **Reject exact portal request**. Expect **REJECTED**, no committed publication
   and no download. Inspect its separate decision execution and note both IDs.

If creation fails, approval expires, publication stays APPROVED, or an outcome
is uncertain, stop and inspect the stored request. Do not blindly replay, renew,
restart or redeploy. Fresh manual outcomes are required for the P1 recording.

## Exact local workflow and successful execution links

These URLs are for the owner's existing environment, not remote employer access.
P6-B did not recheck service availability or run any Docker/LLM operation.

| Stage | Manual parent | Successful child executions |
| --- | --- | --- |
| P2 | [Native tools](http://127.0.0.1:15690/workflow/p2-read-agent-demo-v1) | [KPI#88](http://127.0.0.1:15690/workflow/p2-read-agent-core-v1/executions/88), [Quality#90](http://127.0.0.1:15690/workflow/p2-read-agent-core-v1/executions/90), [Combined#104](http://127.0.0.1:15690/workflow/p2-read-agent-core-v1/executions/104) |
| P3 | [MCP](http://127.0.0.1:15690/workflow/p3-mcp-agent-demo-v1) | [KPI#94](http://127.0.0.1:15690/workflow/p3-mcp-agent-core-v1/executions/94), [Combined#106](http://127.0.0.1:15690/workflow/p3-mcp-agent-core-v1/executions/106) |
| P4 | [RAG](http://127.0.0.1:15690/workflow/p4-rag-demo-v1) | [KPI#98](http://127.0.0.1:15690/workflow/p4-rag-core-v1/executions/98), [Cancellations#100](http://127.0.0.1:15690/workflow/p4-rag-core-v1/executions/100), [Combined#102](http://127.0.0.1:15690/workflow/p4-rag-core-v1/executions/102) |

For a later separately authorized live run: edit **Question** on a manual parent,
then **Execute workflow**. Never execute guarded cores directly. Run sequentially.
Detached P2 API/P3 MCP may need authorized recovery after a reboot; preparation
is not authorization for additional recovery or inference.

## Seven screenshots to capture manually

1. README architecture and truthful stage status.
2. Fresh P1 PUBLISHED result and matching local publication receipt/decision ID.
3. Different fresh P1 REJECTED case and absence of publication.
4. P2#104: AI Agent two actual tools and fact provenance.
5. P3#106: MCP Client Tool, real response and checked cancellation facts.
6. P4#102: retrieved chunks/source IDs and validated answer/citations.
7. Engineering proof: CI definition labelled hosted run pending, evaluation
   denominators, public API artifacts and verified logging correlation receipt.

An engineering composite may combine reviewed crops. No successful hosted CI
screenshot exists yet; add one only after authorized publication and an actual run.

## Privacy and publication

- Never show executions **#6/#8**: they contain the revoked demo token and must
  remain private/retained. Do not export raw execution history. Failures #92/#96
  remain failure evidence, not successful demonstration results.
- Hide credential/authentication/header panels, cookies, browser Network/Storage
  tools, terminals, .local/config/environment files, DSNs, login screens, Windows
  account paths and private browser tabs. Inspect each chosen output before capture.
- Show only reviewed policy chunks, demo case IDs and aggregate facts. Hide raw
  transactions, customer IDs, historical WP2/WP4 resources and unreviewed logs,
  exports or downloaded JSON. Review every video frame and screenshot manually.
- Logging: show P6-A's safe response/event match receipt and allowlisted logger
  source. Label synthetic examples synthetic. No full distributed tracing claim.
  Swagger/ReDoc are disabled: show reviewed OpenAPI JSON and blank Postman
  templates instead. Do not expose authenticated runtime schema or tokens.
- Screenshots remain Git-ignored pending visual privacy review. Static publication
  checks cover forbidden paths and known secrets, not universal privacy detection.
- An employer should understand the project through README, source/workflows,
  safe evidence, evaluation methodology, API artifacts and the short video;
  local setup is optional. Add reviewed media and the final video URL when ready.
- Before publication: confirm fresh manual P1 outcomes, review media and licensing,
  rerun publication preflight, establish GitHub owner/repository/visibility and
  obtain explicit commit/publication authorization. Hosted CI and Postman import
  remain pending. No production, general model accuracy, CD or savings claims.

Receipts: [initial live validation](../evidence/p6_live_validation.json),
[Combined repair](../evidence/p6_combined_repair.json),
[prior P1 browser checks](../evidence/p12_human_approval.json).
Next: owner review and recording preparation. P6-C has not started.
