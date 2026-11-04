# v0.1 specification

## Scope clarification (4 November 2026)

This is the original v0.1 design and dated implementation history, retained for
traceability. Proposed endpoints, state vocabularies, deadline rules and statements
that a component was not implemented describe that earlier scope; they are not
an authoritative description of today's deployed interfaces or acceptance contract.
The completed portfolio has P1-P5/F1-F6 and controlled local Human Approval.
See [current scope](README.md), [requirement statuses](docs/REQUIREMENTS_MATRIX.md),
[acceptance](ACCEPTANCE.md) and the [public API guide](docs/API_DEMO_GUIDE.md).
The broader historical gates are not all claimed as passed.

<details>
<summary>Original specification and historical checkpoint notes</summary>

Owner-bound manual pilot (2026-10-06): one native-owner-approved synthetic request produced one server-accepted/committed publication through separate inactive/manual n8n execution63 before its original exclusive deadline. Exact automated owner export4129 bytes/hash/filename passed; worker stopped/removed/pilot unbound, main/M02 unchanged. No contract/deadline/approval transfer/reset or automatic schedule change; native published-page/download QA and populated/coordinated recovery/clean import/broader pilot/release remain open. Evidence: private historical evidence (not published).

Assembled synthetic UAT (2026-10-06): fixed18082 boundary and cookie namespace, closed config/effective privilege checks and owner-only listener/actual HTTP/restart verified. Browser fixture pending, separate automated synthetic probe decision only, zero publication/worker/n8n activation; main/M02 unchanged. Native-browser UAT/pilot and populated migration/coordinated recovery/clean import/release remain open. See private historical evidence (not published); no business deadline or approval-transfer change.

Deployment preparation (2026-10-06): fixed-target read-only preflight preserves main20/M02 and idle n8n while deliberately returning deployment BLOCKED. private historical evidence (not published) documents exact pins, isolated synthetic UAT/role/migration order and required coordinated snapshot/single-writer restore fences; it does not implement populated deployment admission or close a release gate. Next assembled owner/worker listener with strict per-port origin/startup fences and native-browser UAT. No contract/deadline/approval-transfer change.

Isolated n8n restore (2026-10-06):142 public metadata tables/sequence last values and16 home file bytes match in an independent internally networked clone. Recovered key/config/settings support two actual authenticated canary HTTP/external-runner executions; missing key blocked before startup, wrong key fails real credential decryption. No decrypted export/business action/main deployment/old-writer admission. Next bounded deployment preflight; whole coordinated recovery/custody/browser/pilot remain open. See private historical evidence (not published).

Isolated crash/business restore (2026-10-06): nine actual API/n8n/dedicated-PG interruption and independent-cluster retail-row restore scenarios passed on unchanged029/API/workflow. Original action/key/hash/deadline/history and committed slots survive; restored roles disabled, fresh worker credentials, separate explicit quarantine before admission. No portable pg_xact_status assumption, approval/renewal/reset or main activation. Whole n8n metadata/key/config restore, generic admission/deployment/browser/pilot remain open; see private historical evidence (not published).

Isolated durable n8n v2 (2026-10-06): a separate inactive null-plan workflow uses actual execution IDs, deterministic same-slot reservation keys, acknowledged committed grants plus fresh GET before acceptance, and GET before success. Unchanged029 enforces three committed slots across reruns; the workflow separately caps32 HTTP node calls/run, bounded Retry-After and stale-lease recovery. Fifteen actual n8n/private HTTP/synthetic SQL scenarios and sanitized export roundtrip passed. Worker-only installer needs no operator credential. Main/M02/old028 workflow unchanged; crash/restart/restore/deployment/browser/release remain open. See private historical evidence (not published).

Isolated attempt API follow-up (2026-10-06): `api/portal_attempts.py` adds fixed service state/reserve/accept/report/reconcile and separate operator-only recovery over unchanged029. Exact projection/binding/type/clock checks precede commit, unknown acknowledgements return sanitized503, GET/other active execution cannot grant new acceptance. No auto retry/renewal/reset, main/listening/n8n activation or genuine execution provenance yet. See private historical evidence (not published).

Isolated durable attempts follow-up (2026-10-06): migration029 records bounded committed reservation slots, fixed execution/outcome/actor metadata and authoritative original-key reconciliation under existing case locks. No same-transaction reservation/acceptance, stale lease replacement, reset or expiry extension; separate operator recovery cannot publish. This is SQL foundation only, not HTTP-call/backoff budget or n8n/main integration. See private historical evidence (not published) for verified checks and remaining scope.

Isolated worker/n8n follow-up (2026-10-06): migration028 adds two fixed original-key state/exact-bound acceptance wrappers; separate worker bearer cannot approve/renew or use legacy dispatch. Inactive manual null-plan workflow reads before each write/reconciles after commit, at most three POSTs/four reads per execution. 90 SQL/ASGI/unit tests, VM policy and eight actual n8n/private HTTP/SQL scenarios pass, not main activation/full release. Durable SQL attempts/unknown/dead-letter and cross-rerun retry budget remain next. See private historical evidence (not published).

Isolated auth follow-up (2026-10-06): migration 027 and explicit five-login installer reuse signed native owner login/logout with fresh absolute-hour session authorization. Three fixed auth functions, separate from review/issuance/acceptance; no sliding request deadline, automatic approval/renewal or main activation. 22 SQL/ASGI +2 registry units +135 regressions pass; unknown auth acknowledgement issues no new session cookie. Orphan committed login sessions may consume cap until expiry/revocation. Native-browser UAT, n8n/deployment/restore/release remain open. See private historical evidence (not published).

Isolated transition API/provenance follow-up (2026-10-05): migration 026 and explicitly isolated installer add service-only exact-bound transition POST/original-key GET reconciliation, owner committed transition/unchanged retired v2 history, and separate hash-bound provenance before new-target confirmation forms. No old controls/approval conversion/file adoption/automatic publication. Twenty-five new actual-login/SQL/ASGI/boundary checks +110 categorized regressions pass; main stays migration 20/M02 unchanged. Login/logout integration, n8n/deployment/restore/browser UAT remain later. Evidence: private historical evidence (not published); no full release pass.

Isolated legacy transition follow-up (2026-10-05): migration 025 permits only an explicit same-case latest-expired-unreviewed legacy v2 request -> first fresh portal v3 request, with separate immutable old/new hash-bound provenance, atomic retirement/request audits, new full 86400-second deadline and fresh owner approval. Any old decision/outbox/v1 proposal blocks transition; old writes are fenced under the same case lock. Twenty-four new tests +86 categorized regressions pass, not main/live deployment, service HTTP/provenance UI, browser UAT, physical completion or full release acceptance. See private historical evidence (not published).

Isolated new-target review follow-up (2026-10-05): migration 024 and native confirmed owner forms/current-history pages plus service-only issuance have 20 actual-login/SQL/ASGI checks and 67 categorized regressions. Exact case/report/request/target/deadline/CSRF, commit-before-redirect, expired-approved successor/fresh approval and no view/approval publication are covered. Main does not import/install these routes; no real renewal/approval/publication, legacy conversion, listening HTTP/browser QA or release pass. See private historical evidence (not published).

Isolated owner-read/commit adapter follow-up (2026-10-05): migration 023 and three test-app GET routes verify committed publication receipts and exact owner-only exports, not draft/approved-only downloads. Commit-before-return, real commit plus simulated acknowledgement loss, deferred SQL failure, fresh session/revocation checks and fixed browser boundaries have 18 mixed real-DB/ASGI/boundary tests; 18 foundation SQL and 31 unit/mock regressions pass separately. Main remains migration 20, no new runtime route/worker or real publication. New-target issuance/decision UI, legacy transition, deployment and restore remain open; see private historical evidence (not published). Prior implementation checkpoints below are retained history.

Isolated implementation follow-up (2026-10-05): migration 022's new-target requests/owner-session decisions/immutable exact-content outbox/guarded acceptance/audit passed 18 actual PostgreSQL/scoped-login tests. Fresh acceptance time, exclusive expiry, delayed commit/rollback/audit fault, concurrent successors, replay and revocation are covered; main migration 20 and real M02 unchanged. New-target API/UI/export/worker and legacy transition remain unimplemented, no activation/full release pass. See private historical evidence (not published).

Selected publication direction (2026-10-05, owner-delegated choice): future target `local-owner-portal-report-v2` uses a PostgreSQL-authoritative in-window server-acceptance event, effective only on eventual transaction commit; JSON is later owner-authenticated export. Acceptance before the original 86400-second deadline is distinct from commit acknowledgement/page/file completion. New request/policy/decision/intent bindings require fresh owner approval; legacy physical-file requests remain unchanged. Contract selected, implementation/test/deployment pending; no real publication enabled. See private historical evidence (not published). Earlier physical-deadline checkpoints below remain evidence/history, not the new target's acceptance semantics.

Corrected owner native follow-up (2026-10-05): all seven synthetic Windows/SQL tests pass, including actual process-exit/receipt recovery. The deliberate final-authorization/pause diagnostic confirms an after-deadline matching write, not safety. The owner confirms both decision and publication must complete before the same request-created_at + 86400-second exclusive deadline. Even an approved-but-unpublished report needs a new request and fresh owner approval after expiry; current terminal-approved successor recovery is not implemented. Real dispatch remains BLOCKED; no grace period, deadline/lease extension or activation. See private historical evidence (not published) and private historical evidence (not published).

Native-harness follow-up (2026-10-04): fixed private Docker IPC preserves actual SQL transactions across host calls, without host dependencies or DB ports. Four actual IPC/SQL/process-close checks pass with memory files; seven owner-run combined Windows tests are prepared, not verified. The diagnostic final-authorization/pause counterexample blocks activation; no full FR-10/FR-11/AC-18 pass or real publication. See private historical evidence (not published).

Status: planned. Implementation starts after G0. Scope budget: 40 focused human/project hours after G0; see `ROADMAP.md`. This is a delivery budget, not a claim that implementation will fit without scope decisions.

## End-to-end scenario

An analyst requests a sales report for an explicit date range. The system selects the verified archive version, checks data, builds SQL metrics, generates deterministic findings, optionally adds a validated local-LLM commentary, and prepares an immutable report revision. An authorized reviewer approves or rejects that revision. Only an approved revision is published locally. Every transition has a case ID and audit event.

Connected GitHub/Telegram actions are an optional v0.1+ increment. They must not block the first offline approval/report demonstration. Outbox and uncertainty behavior are implemented and tested before enabling a real connector.

## Interfaces and units

- `POST /api/v1/report-requests`: validated JSON and a request idempotency key; returns case ID.
- `GET /api/v1/cases/{case_id}`: state, safe status, report revision, and evidence references.
- `POST /api/v1/cases/{case_id}/decision`: authenticated reviewer decision on an exact proposal.
- `GET /api/v1/reports/{report_id}`: approved artifact, with an immutable hash.
- `GET /healthz` and `GET /readyz`: liveness and readiness without secret/configuration dumps.
- A signed n8n webhook invokes the request contract; manual and schedule triggers use the same normalized contract.
- All API timestamps use an explicit UTC offset. Source timestamps are preserved separately under `DATA_CONTRACT.md`.
- Secrets are configured locally; credential binding/export procedures are documented for the pinned n8n version.

These are target contracts. Generate OpenAPI from the actual service and test it; this file does not claim those endpoints already exist.

WP2 now has the separately named bounded `POST /api/v1/calculations/comparison`, plus `/healthz`, authenticated `/readyz` and generated/authenticated `/openapi.json`, tested on the existing local dependency image. See private historical evidence (not published). It calculates but does not create a case or satisfy the report-request/review/publication contracts above. It requires RFC3339 offsets and explicit acknowledgment of the assumed source timezone, conservatively validates observed archive bounds and rejects unsupported DST periods.

Migrations 013–014 additionally implement bounded `POST /api/v1/report-requests`, `GET /api/v1/cases/{case_id}` and authenticated draft-only `GET /api/v1/cases/{case_id}/revisions/{revision}`. See private historical evidence (not published). The same request body plus one `Idempotency-Key` header binds a durable case; completed replay returns 200, busy/pending acceptance 202 (repeat the same POST to resume), and a changed request under that key 409. Only `received` and `awaiting_approval` plus immutable deterministic revision 1 are implemented. No human decision, approved artifact or outbox is enabled. Case/audit timestamps have UTC offsets; separately labelled source-clock request/report timestamps remain naive.

The later manual-only `workflows/wp3_manual_draft.json` connects those endpoints in n8n 2.40.0 and verifies the draft's binary bytes/hash without JavaScript monetary conversion. Two actual frozen-M02 executions replayed one case/revision, and six isolated HTTP test-double executions verified bounded retries/rejections; see private historical evidence (not published). It has no secret values/bindings in its sanitized export, no model call and no approval/publication. Human review, general inputs, signed webhook/schedule, reusable sub-workflows and complete release acceptance remain open.

Migration 019 adds staged fixed SQL decision/receipt functions and immutable decisions/audit/publication intents. Only a new NOLOGIN role receives their grants; no runtime/API/UI activation or real decision/publication occurs. Rolled-back SQL fixtures verify binding, exclusive expiry, replay and atomicity, not independent-connection or end-to-end acceptance. Terminal case/request projections must be integrated before activation; dispatch remains unimplemented. See private historical evidence (not published). This supersedes outbox-unimplemented wording below only for the staged SQL intent foundation.

## Functional requirements

Migration 021 implements staged SQL execution state in a separate append-only ledger, not changes to immutable intent state. Four fixed functions under a NOLOGIN role cover state, claim, fresh authorization and bound observations. Initial/uncertain writes require reconciliation; leases/replays cannot extend the original authorization; at most three write claims. Fourteen isolated actual-login/SQL tests passed with simulated filesystem observations. Main validation remains migration 20; no worker, real dispatch or published projection. See private historical evidence (not published); full FR-10/FR-11 and DB/file acceptance remain open.

The later Python coordinator connects these functions to the file interface only for generated isolated test DBs, rejects autocommit, commits claims first and holds SQL locks through file operations/receipt commit. Mock and real-DB/file-double tests cover rollback, lost commit acknowledgement and stale/expired/revoked authorization. No worker/route/main migration/native DB-file integration or complete FR-10/FR-11 pass; hard deadline fencing across a process pause remains unproved. See private historical evidence (not published).

Migration 020 enables confirmed owner-session decisions/receipts under `/portal/.../decision` and derived terminal case/request projections. The portal role has nine fixed functions, no direct table/issuance rights; service/bearer routes cannot decide. Physical draft rows/report bytes stay unchanged; approved/rejected metadata comes from the complete review ledger. ASGI/actual-login/independent-connection and live denial/restart tests passed, not native approval of M02. No dispatcher/publication exists; see private historical evidence (not published). Earlier staged/decision-unimplemented paragraphs are historical checkpoints.

Migration 016 implements separate owner bearer GETs under `/review/v1/`; migration 017 adds read-only `/review/v2/` current/history request projections. Their dedicated login has fixed reads only; n8n and owner credentials cannot substitute for each other. One owner mapping, 86400 policy and unapproved M02 v2 request exist. See private historical evidence (not published) and private historical evidence (not published). This is not browser login/session/CSRF or owner-observed review/decision/publication.

Migration 018 now adds the separate fixed-loopback `/portal` browser surface: signed five-minute login CSRF, one-hour absolute PostgreSQL sessions, fresh-login rotation, session-derived logout CSRF, owner revocation rechecks and immutable successful auth events. A dedicated seven-function role writes auth state only; cookies cannot authorize `/api/` or `/review/`. List/request/draft inspection is read-only; no decision/renewal/publication controls exist. Automated SQL/login/HTTP/restart and public-login-page visual checks passed, not owner-performed sign-in or authenticated-page visual QA. Plain HTTP/inherited ACL limitations remain explicit in private historical evidence (not published).

The later authenticated `GET /api/v1/cases/{case_id}/revisions/1/preview` renders immutable unapproved drafts using Decimal display and hash/schema/provenance validation. The loopback route and private credential-free HTML helper have current-environment tests; visual QA was blocked by browser file-protocol policy. See private historical evidence (not published). This is not the target approved-report endpoint or a human decision/publication. Service authentication does not establish reviewer identity.

| ID | Requirement | v0.1 evidence |
| --- | --- | --- |
| FR-01 | Import a pinned archive completely; preserve file hash, worksheet, source row number and raw values | G0 profile and import audit |
| FR-02 | Classify accepted sales, cancellations, other adjustments and invalid rows without fabricating data | Fixture and real-data reconciliation |
| FR-03 | Compute the approved KPI definitions in SQL using NUMERIC | Independently checked golden examples |
| FR-04 | Accept a period and replay/as-of cutoff; prevent future data leaking into the case | Boundary and later-period tests |
| FR-05 | Generate a deterministic report before any LLM call | Same case succeeds with AI disabled |
| FR-06 | Request bounded structured commentary from a local model using supplied metric/evidence IDs | Real Ollama response and validation logs |
| FR-07 | Reject unsupported claims, unknown references, invalid JSON and numerical contradictions | Negative AI-output tests |
| FR-08 | Persist report revisions and review state | Restart and concurrent decision tests |
| FR-09 | Require valid human approval of payload hash, version, target and expiry | Approval acceptance suite |
| FR-10 | Publish an approved report exactly once per logical local action | Transaction/unique key and retry evidence |
| FR-11 | Keep an outbox, bounded retries, dead-letter records and a recovery path | Fault injection and operator recovery |
| FR-12 | Expose normalized API/webhook contracts with least-privilege access | Auth, signature and contract tests |
| FR-13 | Export sanitised n8n workflows with tested reusable sub-workflows | Clean-instance import |
| FR-14 | Record effort/elapsed/quality observations for the three measurement variants | Ten-case pilot log |
| FR-15 | Provide English documentation, an initial diagram, screenshots and a short demo | Release evidence index |

## Quality and resource requirements

| ID | Requirement |
| --- | --- |
| NFR-01 | Required runtime incurs no mandatory subscription or paid API charges; no automatic paid fallback |
| NFR-02 | Pinned compatible images/packages/model revisions; no floating `latest` in a released configuration |
| NFR-03 | Only required local UI/API ports bind to loopback by default; database/model services stay private |
| NFR-04 | Same snapshot, period and policy version produce identical deterministic metrics |
| NFR-05 | Repeated input and concurrent approval callbacks cannot duplicate a local business action |
| NFR-06 | No secret appears in Git, workflow exports, logs or normal test artifacts |
| NFR-07 | Capture memory, import duration, model latency and API latency; set limits from measured G0 results |
| NFR-08 | Model unavailability gives an explicitly labelled deterministic/manual-review result |
| NFR-09 | Recover persisted cases after process restart; validate one basic backup/restore before v0.1 release |
| NFR-10 | Every published metric and material AI observation is traceable to source/policy evidence |
| NFR-11 | Entire project and public-facing output are in English; source data values remain unchanged |

## State and persistence

WP4 preparation now uses migration-017 service-only POST `/api/v2/cases/{case_id}/approval-requests`, one scoped `Idempotency-Key`, expected integer revision 1/exact report SHA-256 and explicit null-or-UUID predecessor. SQL binds reviewer/policy/24-hour expiry/action/target/content and predecessor hash/generation. Same-key replay preserves identity/deadline; a new key can replace only the latest expired request. Current/ID service and owner GETs never renew. V1 GETs remain historical; POST is retired with 410 and its runtime SQL grant revoked. Existing v1 proposals require an explicit legacy transition before v2 issuance. No caller identity/URL/TTL is accepted. See private historical evidence (not published) and private historical evidence (not published); human decisions/approved reports/outbox remain unimplemented.

Case states: `received`, `validating`, `calculating`, `drafting`, `awaiting_approval`, `approved`, `rejected`, `expired`, `published`, `needs_attention`, `failed`. AI-disabled runs skip `drafting` but retain the same report contract.

Outbox states: `pending`, `in_progress`, `succeeded`, `retryable`, `unknown`, `dead_letter`, `cancelled`.

Tables include source snapshots, import jobs, raw invoice lines, quality findings, metric runs, cases, report revisions, evidence references, approvals, outbox actions, audit events, and measurement runs. Use foreign keys and unique business keys. Keep the n8n application database separate from project business schemas/credentials.

## AI contract

Return a schema-versioned object with `case_id`, `report_version`, a short summary, observations, limitations and an abstention flag. Each observation contains provided evidence IDs and metric IDs. The LLM does not generate executable SQL, action targets, credentials or authoritative calculations. A deterministic validator resolves references and checks copied values.

Maximum one initial model request and one repair request per report by default. A repair must remain within the same bounded context. Further failure routes to deterministic output/manual review, not an infinite prompt loop.

## Approval and action

Store canonical payload bytes or an unambiguous canonical serialization. Hash includes report revision, action type, destination and content. The identity is established by authentication, not a username field supplied by the caller. Any changed payload requires new approval. Consume the approval and enqueue the action atomically. Revalidate immediately before dispatch.

The v0.1 business action is immutable local report publication. If a GitHub connector is enabled, reconcile a timeout using a deterministic action marker before considering another POST. Unknown outcomes are not blind retries.

Owner-confirmed pilot rule, 2026-10-01, clarified 2026-10-05: only the owner reviews; both decision and publication must complete strictly before request creation + 86400 elapsed seconds. Approval does not restart the clock. At/after expiry an approved-but-unpublished report requires a new immutable request and fresh owner approval; viewing/delivery/retries cannot reset the deadline or reuse the old approval. Current v2 replacement evidence covers expired unapproved requests only; expired-approved successor recovery remains planned. No automatic real renewal is performed. Browser/decision evidence is described in the later WP4 checkpoints above; real M02 remains unapproved/unpublished. No chat policy message, login or automated token check approves M02.

## Deliverables

Working core Compose configuration, secure local bootstrap, migrations, service code, exported workflows, meaningful tests, pinned dependencies, a ten-case pilot, readable BPMN 2.0 models, minimal ERD/architecture, README and a 2–3 minute English demo. Every unimplemented capability stays visibly planned.

</details>
