# Technology roadmap

The broad technology goal is preserved. **Core** is the first release; **extend** is a bounded later feature; **lab** is a separate experiment admitted by a concrete question. Nothing in this table is marked implemented. License notes are selection leads, not legal clearance for every version or commercial offering. Confirm exact versions/weights in G0 or before that profile is enabled.

| # | Block | Components | Stage | Purpose / evidence | Free-edition constraint |
| --- | --- | --- | --- | --- | --- |
| 1 | Orchestration | n8n Community; optional Registered Community | Core | Business process, triggers, sub-workflows, errors | Sustainable Use License; no mandatory paid features |
| 2 | Code execution | n8n external task runners; JavaScript/Python | Core / extend | Short bounded transformations; runner isolation | Pin compatible n8n/runner versions |
| 3 | Database | PostgreSQL / SQL | Core | Facts, state, approval, audit and outbox | PostgreSQL License |
| 4 | Vector index | pgvector | v0.2 | Local retrieval attached to authoritative source IDs | PostgreSQL License |
| 5 | Alternate vector store | Qdrant OSS | Lab | Same-query retrieval comparison | Apache-2.0 candidate; not a parallel source of truth |
| 6 | Local LLM | Ollama; candidate Qwen3-4B | Core | Structured commentary; tools later | MIT runtime / Apache-2.0 weights; verify chosen revision |
| 7 | Embeddings | Qwen3-Embedding-0.6B candidate | v0.2 | Local embeddings for a justified retrieval task | Apache-2.0 candidate; measure fit |
| 8 | Reranking | Qwen3-Reranker-0.6B candidate | Lab | Measure improvement over fixed retrieval baseline | Apache-2.0 candidate; load sequentially if needed |
| 9 | Native agent | n8n AI Agent; PostgreSQL state | v0.2 | Model-driven bounded tool selection | Actual tools/state tests required |
| 10 | Alternate orchestration | LangGraph / necessary LangChain adapters | Lab | Checkpoints and interrupt/resume comparison | OSS libraries; no required hosted tracing |
| 11 | MCP | FastMCP; n8n MCP client/server | v0.2 | Own KPI/evidence tools plus meaningful external tools | Protocol/version/auth compatibility must be exercised |
| 12 | External MCP | GitHub MCP; optional Playwright MCP | v0.2 / lab | Read actual owner-repository context; browser checks | Scoped access; provider/API quotas apply |
| 13 | Agent-to-agent | A2A / official Python SDK | Lab | Isolated verifier task with status/result/cancel | Protocol adapter, not a claimed native n8n node |
| 14 | Agent Skills | Versioned allowlisted SKILL.md format | Lab | Repeatable instructions and policy lookup | Do not assume automatic n8n support or run arbitrary skill code |
| 15 | Backend/contracts | Python, FastAPI, Pydantic, JSON Schema/OpenAPI | Core | File/API/auth contracts and validators | Local open components; pin exact versions |
| 16 | API protocols | REST, HTTP/JSON, webhook; GitHub GraphQL | Core / extend | Read/write integration, pagination and authentication | Use real services; protocol itself does not imply free API |
| 17 | Data processing | pandas; SQL; DuckDB | Core / extend | File parsing, primary calculation, independent cross-check | Pandas BSD / DuckDB MIT candidates |
| 18 | Transformations | dbt Core + PostgreSQL adapter | v0.2 | Versioned marts, tests and lineage | Pin free Core/adapter; no paid cloud dependency |
| 19 | Quality | Pandera + dbt tests | Core / extend | Pandera at ingest; dbt on marts | Separate roles rather than duplicate checks everywhere |
| 20 | Statistics | scikit-learn / statsmodels | Extend | Compare anomaly/segmentation rules with simple baselines | Time-based evaluation; no untested causal/forecast claim |
| 21 | GraphRAG | PostgreSQL relations + NetworkX + RAG | Lab | Relationship queries only if simpler retrieval is inadequate | No mandatory graph SaaS or paid extraction |
| 22 | Document processing | Text/HTML parser; Docling; Tesseract | Lab | Parse actually needed permitted documents/scans | Check parser and each weight license separately |
| 23 | BI | Metabase OSS | v0.2 | Business metrics and process dashboard | AGPL edition; no paid embedding/SSO |
| 24 | Process mining | PM4Py | Extend | Analyse our own genuine automation event log | AGPL candidate; not the historical shop work process |
| 25 | Queue | Redis Open Source + n8n worker | Lab / justified operations | Backpressure and worker-crash recovery | Select an available free license; use file pointers, not unsupported binary storage |
| 26 | Alternate broker | Valkey | Lab | Compatibility experiment against same queue case | BSD candidate; compatibility is not assumed |
| 27 | Observability | OpenTelemetry, Prometheus, Grafana OSS | Extend | Operational latency/errors/alerts, separate from BI | Apache-2.0 / Grafana AGPL candidates |
| 28 | AI tracing | Langfuse OSS core | Lab | Prompt/model/tool traces and evaluation comparison | MIT core candidate; account for all service dependencies |
| 29 | Heavy storage | ClickHouse OSS; SeaweedFS S3 | Lab | Optional trace analytics/blob backend | Apache-2.0 candidates; actual S3 compatibility test |
| 30 | Identity | Keycloak | Lab | OIDC for our own API/portal | Apache-2.0 candidate; does not unlock n8n SSO |
| 31 | Policy | Python allowlist first; OPA/Rego later | Core / lab | Deterministic action/tool constraints | No mandatory OPA server for baseline |
| 32 | Email | Mailpit / SMTP | Extend | Local mail formatting and delivery test | MIT candidate; external delivery is separate |
| 33 | Tests | pytest; Hypothesis; Schemathesis | Core / extend | Business logic, properties and contracts | Small meaningful checks; no implementation-mirroring test inflation |
| 34 | UI/load tests | Playwright; k6 OSS | Extend | Review UI and bounded concurrent failure scenarios | Apache-2.0 / k6 AGPL candidates; no cloud load service |
| 35 | AI evaluation | Small Python runner; optional Ragas | Core / lab | Quality/abstention/retrieval/tool metrics | Explicit local models; no default paid judge |
| 36 | Supply chain | Gitleaks; Trivy; Syft/SBOM; OSV | Core / extend | Secrets, versions/licenses and vulnerabilities | Free local tools/public APIs, freshness recorded |
| 37 | Deployment | Docker Engine/Compose; personal Docker Desktop | Core | Reproducible resource-bounded profiles | Desktop terms vary by usage; no universal free claim |
| 38 | Versioning/CI | Git; GitHub Free; standard Actions runners | Core / extend | History, exports, focused checks and releases | Use public standard-runner allowances; verify limits before CI |
| 39 | BA/SA modelling | BPMN 2.0, DMN, C4, ERD, sequence/state diagrams | Core / extend | Explain requirements, process, data and decisions | Diagrams must agree with behavior; actual BPMN files required |
| 40 | Demonstration | Local review UI; JSON demo; GitHub/video | Core / v0.1+ | Low-friction inspection and full reproducibility | No perpetual free public hosting promise |

## Admission rules

Each extension records its business/engineering question, simpler baseline, time/resource budget and result. A comparison without an actual run remains documented, not implemented. Make/Zapier/Power Automate may be compared in an ADR; no paid account or claim of hands-on use is required. Kubernetes, Kafka and Spark are not added just to fill a technology list.

## Optional currency/API experiment

Frankfurter REST/MCP can demonstrate historical FX retrieval without making EUR conversion a false business need. Include it only as a labelled management-reporting assumption or laboratory connector. Core reports remain GBP. Provider conditions and historical-rate coverage must be checked before a new run.

## Paid or incompatible capabilities

No JEV, paid n8n Git/environments/SSO/sharing, enterprise binary storage, managed GPU, paid evaluation judge or trial-only service is a core dependency. Ordinary Git tracks exported workflows. A local role system does not grant enterprise n8n features. Free registration features are optional.

## Evidence status

A component can be planned, documentation-verified, locally verified, blocked, or deferred. Promote a status only with dated version/environment/command/evidence. Published API pricing can change; a disabled optional connector must not trigger billing as fallback.
