# n8n capability coverage

Goal: broad coverage of relevant free capability families, not a claim to implement every node, paid feature, or possible service integration. Map actual node names and versions during implementation.

| Family | Demonstration | Stage |
| --- | --- | --- |
| Triggers | Manual report, schedule, signed webhook; polling integration later | Core / extend |
| Data | JSON expressions, mapping, split/aggregate, merge, validated types | Core |
| Control flow | IF/Switch branches, bounded batching/loops, waits and timeouts | Core |
| Reuse | Ingestion, validation, audit, error and action sub-workflows | Core |
| Code | JS Code node; external runner; Python API boundary | Core |
| Files | Real workbook import through service; report exports and safe artifact references | Core |
| HTTP | Requests without ready-made nodes, pagination, auth, rate limits and response checks | Core / extend |
| Databases | PostgreSQL read/write and validated transaction APIs | Core |
| AI | Local model call, structured output, validation and fallback | Core |
| Agents | Actual tool selection, state, constraints and review | v0.2 |
| RAG | Ingestion, retrieval tools, citations, update and delete | v0.2 |
| MCP | Client calls and a controlled server tool surface | v0.2 |
| Reliability | Error workflow, Stop And Error, bounded retries, dead-letter, restart/replay | Core |
| Credentials | Least privilege, local encryption key, sanitised exports, OAuth later | Core / extend |
| Operation | Health, pruning, backup/restore; monitoring/queue workers later | Core / lab |
| Registered features | Optional folders, debug in editor, custom execution metadata | Optional after registration/test |
| Small lookup data | Optional Data Tables for non-authoritative demo/configuration data | Optional |

Candidate workflow responsibilities: intake, ingestion, quality, calculation, drafting, approval request, publication/outbox, reconciliation, error handling, and evaluation. Add retrieval, agent reasoning, notification, monitoring and backup orchestration when their release is admitted. A useful sub-workflow has an input/output contract, not just an extra node count.

Community does not provide all paid collaboration, source-control, SSO, external-secret or binary-storage features. Use ordinary Git exports, the application's own authorization and local file references under their correct names. Verify edition/version capabilities before implementation; do not simulate an enterprise feature and claim it as native n8n functionality.
