# Published n8n workflow exports

These are sanitized source definitions for the existing local portfolio, not a
self-contained installation. Real credentials, sessions, database state, raw
execution history, deployment/recovery configuration and legacy WP4 attempt/
publication templates remain withheld. A credential ID/name is a reference, not
an authentication secret or a grant of authority.

## Current portfolio definitions

| Export | Workflow ID | Role |
| --- | --- | --- |
| [F2 creation entry](f2_create_report_staged.json) | p12-create-report-v1 | Manual trigger plus signed-webhook verification/admission gate before the existing report core. The filename records its staging origin; controlled F2 deployment subsequently completed. |
| [Original P1.2 parent](p12_create_report.json) | p12-create-report-v1 | Earlier manual-only baseline. Same ID as the F2 definition: these are alternative versions, not separate workflows to import together. |
| [Report core](p12_report_core.json) | p12-report-core-v2 | Guarded deterministic report/request creation, bounded request handling and exact draft/hash validation. |
| [Human decision](p12_human_decision.json) | p12-human-decision-v1 | Reads the committed decision, publishes only an approved report and returns the actual result. Rejection may execute this workflow without publication. |
| [P2 manual parent](p2_read_agent_demo.json) | p2-read-agent-demo-v1 | Manual question selection and core invocation. |
| [P2 agent core](p2_read_agent_core.json) | p2-read-agent-core-v1 | Native AI Agent, local Ollama and Sales KPI/Data Quality read-only tools. |
| [P3 manual parent](p3_mcp_agent_demo.json) | p3-mcp-agent-demo-v1 | Manual question selection for MCP analytics. |
| [P3 MCP core](p3_mcp_agent_core.json) | p3-mcp-agent-core-v1 | AI Agent with supported MCP Client Tool and bounded result validation. |
| [P4 manual parent](p4_rag_demo.json) | p4-rag-demo-v1 | Manual question selection for RAG. |
| [P4 retrieval/agent core](p4_rag_core.json) | p4-rag-core-v1 | Embeds the question, searches pgvector before the agent, validates structured answers/source IDs and constructs citations. |
| [P4 indexing](p4_rag_index.json) | p4-rag-index-v1 | Loads and chunks policy documents, creates real embeddings and stores pgvector chunks. This writes the corpus and is not a read-only smoke check. |

## Retained historical examples

- [P1.1 manual draft](p1_manual_report.json), ID raa-p1-demo-draft-v1.
- [Earlier WP3 manual draft](wp3_manual_draft.json), ID raa-wp3-manual-draft-v1.

These illustrate earlier deterministic report/draft work. They are not the current
F2 creation entry; the old P1.1 token was revoked. Historical filenames/credential
references are not instructions to restore obsolete credentials or run a workflow.

## Evidence and portability

[P1 approval evidence](../evidence/p12_human_approval.json) records the earlier
P1.2 integration. [Initial P6 checks](../evidence/p6_live_validation.json) retain
failed Combined runs; [later checks](../evidence/p6_combined_repair.json) record
the two successful Combined runs, P2 #104 and P3 #106. Read those together rather
than treating the initial failure receipt as current overall status.
[P3 discovery](../evidence/p3_mcp_discovery.json) and
[P4 RAG evidence](../evidence/p4_rag_runtime.json) support the protocol/retrieval
claims. Current F2 owner acceptance and F1-F6 presentation are summarized in
[README](../README.md#verified-tests-and-evidence); no new execution is claimed here.

Importing a definition does not publish/activate it, bind credentials, provision
services or prove a fresh-machine setup. Node URLs, trusted-source IPs and local
service contracts require an authorized provisioned environment. Source exports
are not a live export/certification of today's n8n database settings. Preserve
caller, HMAC, owner and publication guards; never execute guarded cores directly
as a substitute for the parent/owner flow. Use fresh local authority, and request
separate authorization before any indexing, report creation, decision or delivery.
