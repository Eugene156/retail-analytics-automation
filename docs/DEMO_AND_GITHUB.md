# Published portfolio and local demonstration

Status: published and CI-verified on 4 November 2026.

## Public review entry points

- [Repository](https://github.com/Eugene156/retail-analytics-automation)
- [README: scope, architecture and local addresses](../README.md)
- [Demo video](../media/Retail_Analytics_Automation_Demo_GitHub.mp4)
- [Overview screenshot](../media/01-overview.png); the README links all six pages.
- [Hosted CI: successful published commit](https://github.com/Eugene156/retail-analytics-automation/actions/runs/41799269037)

The repository contains 296 approved files, the MIT License, source, sanitized
workflow definitions, six screenshots and the optimized video. Local CI passed
56 pytest tests. No GitHub Release object or automatic deployment is claimed.

## What the demonstration proves

F1-F6 are complete. F2 supports controlled real report creation, authenticated
owner decisions and local publication; creating a report grants no approval.
F3-F5 display verified historical AI/MCP/RAG answers and tool/source evidence.
The [requirement matrix](REQUIREMENTS_MATRIX.md) separates delivered capabilities
from broader partial, deferred and unverified original requirements.

## Pinned policy documents and current status

[DATA_CONTRACT.md](DATA_CONTRACT.md) and [KPI_DICTIONARY.md](KPI_DICTIONARY.md)
are byte-pinned source snapshots for historical P4 embeddings/citations and the
offline evaluator. Their original bytes are preserved by owner decision; editing
status prose would invalidate the source hashes checked against saved evidence.

The data contract's statement that no end-to-end delivered report is claimed
belongs to the earlier WP2 SQL milestone. P1/F2 subsequently implemented and tested
report creation, owner review and local publication. F1-F6 are complete; the
repository and media are public, with 56 local CI tests and successful hosted CI.
That delivery does not establish the broader full point-in-time document/outcome
replay described as future work in the frozen contract.

References inside those two snapshots to unpublished WP2/WP3 notes are private
historical evidence, not accessible public documentation. Use the
[current workflow inventory](../workflows/README.md),
[canonical SQL notes](WP2_CANONICAL_KPIS.md),
[SQL migrations](../db/migrations/008_canonical_period_kpis_v1.sql) and
[current requirement statuses](REQUIREMENTS_MATRIX.md) for public navigation.
No quotations, source hashes, embeddings, model outputs or acceptance receipts
were regenerated for this documentation repair. A future corpus revision requires
separately scoped versioning and evaluation; guards must not be relaxed.

## Local demonstration addresses

The interactive website is local-only. These addresses are for an **already
provisioned owner environment**; they are not public demo links. Use the sidebar
or enter the relevant address:

| Page | Local URL |
| --- | --- |
| Overview | `http://127.0.0.1:18090/overview` |
| Human Approval | `http://127.0.0.1:18082/portal/f2` |
| AI Agent | `http://127.0.0.1:18090/overview#ai-agent` |
| MCP Analytics | `http://127.0.0.1:18090/overview#mcp-analytics` |
| Knowledge Assistant | `http://127.0.0.1:18090/overview#knowledge-assistant` |
| API & CI | `http://127.0.0.1:18090/overview#api-ci` |
| n8n workflow inspection | `http://127.0.0.1:15690` |

Select scenarios to inspect saved answers and expand tool/source evidence.
Human Approval requires manual owner sign-in; new Create/Approve/Reject actions
require owner authorization and publish only to the isolated local target.
Keep credentials, tokens and raw execution exports out of recordings and commits.

P2 API and P3 MCP use detached processes that may need restoration after their
containers stop. Run local model work sequentially on memory-limited machines.

## Workflow portability and setup

[Published workflow exports](../workflows/README.md) reference bounded APIs,
sub-workflows and credentials. They do not contain portable credentials or a
complete bootstrap. Import into a clean n8n instance, zero-credential execution,
fresh-machine deployment/recovery and Postman GUI execution remain unverified.
The original reduced-importable-demo and automatic-bootstrap goals are deferred;
do not imply they are required or validated for reviewing the GitHub portfolio.
Docker profiles, access/recovery material and secrets remain withheld.

The local interactive website requires the existing provisioned environment.
Reviewers can use the published video, source and evidence without installing it.
Do not run creation, approval or publication merely to check availability.

## Media and attribution

Six screenshots were visually reviewed. The owner reports representative review
of 37 distinct video frames at three-second intervals; this is not exhaustive
frame-by-frame verification. Demo request IDs and report hashes are visible.
See the [license](../LICENSE), [third-party notices](../THIRD_PARTY_NOTICES.md) and
[publication inventory](PUBLICATION_MANIFEST.md). Secrets, raw data, runtime state
and private evidence are excluded. Any future media/code publication requires a
new scoped review and owner authorization.
