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
Local CI passed 56 pytest tests; [hosted CI passed](https://github.com/Eugene156/retail-analytics-automation/actions/runs/41799269037).

<details>
<summary>Historical checkpoints preceding the published portfolio scope</summary>

N1 offline implementation acceptance NOT MET (2026-10-10): independent review and mandatory storage blockers (private historical evidence; not published).352 offline tests pass, two physical storage checks blocked; prototypes cannot execute native commands or seal native evidence. Four open security-review categories require implementation and verification. Existing acceptance predicates unchanged; no native fixture or full WP4 acceptance.

N1 readiness blocked (2026-10-10): missing native execution/storage prerequisites (private historical evidence; not published),17 current integration tests/full offline package check pass only. No native evidence/acceptance/resource operation. Historical Windows/dependency failures cannot certify future private storage. All existing Acceptance Criteria/security predicates unchanged and OPEN.

I3 offline fixture integration (2026-10-10): loader/profile/preservation/capture evidence (private historical evidence; not published),335 selected/667 available offline tests and3 workflow VM suites pass. Documented unavailable dependency/Windows publication checks remain unresolved. Bounded AC-18/AC-22/AC-23 preparation only; no native archive/catalog/ACL/scoped API/restore/isolation/runtime proof. All criteria/predicates/gates unchanged and OPEN; stop before N1.

I2 offline preparation (2026-10-10): recipe/planner evidence (private historical evidence; not published),318 tests pass and two full public packages byte-reproduce. Bounded AC-18/AC-22/AC-23 preparation only; no actual SQL/scoped-role/archive/catalog/isolation/restore/native acceptance proof. Existing criteria/security gates unchanged and OPEN. Stop before I3.

I1 offline fixture boundary (2026-10-09): strict contract/context/secret checks (private historical evidence; not published),305 tests pass. Bounded AC-18/AC-22/AC-23 preparation only; no native archive/catalog/restore/SQL API/isolation/admission proof. Existing predicates and all Acceptance Criteria remain unchanged/open; stop before I2.

Safe public checkpoint preparation (2026-10-09): offline safety/reproducibility and limits (private historical evidence; not published). Full public source and empty operational authority verified offline;291 tests pass. This supports bounded AC-18/AC-22/AC-23 preparation only. Frozen003/native008 compatibility, native SQL/catalog/ACL/source/restore/runtime evidence and full WP4 acceptance remain open; no rehearsal or restoration.

Codex/Docker access proposal (2026-10-09): one-shot access and authority-free checkpoint proposal (private historical evidence; not published). Owner host Docker access succeeds; info/ps discrepancy unresolved. Four read-only fixed-context metadata commands proposed through per-command escalation after explicit confirmation, no permanent rules/security changes. Separate public-data fixture needs empty operational authority and reviewed legacy003 report compatibility; not built.0 escalations/native/resource/restore/product-test changes. All gates/WP4 remain open; stop for confirmation.

Native008 preparation diagnostics (2026-10-09): checkpoint and Docker findings (private historical evidence; not published). Public UCI lineage/integrity confirmed, but main dump also contains project authentication/session/request history; full confidentiality/copied-authority safety not certified. Context is local/correct, docker-users enabled, command token Low Integrity; sandbox restriction is the leading access hypothesis, requiring ordinary-terminal comparison. Runtime isolation/engine readiness remain unverified. No restore/rehearsal/config/elevation or product changes; all20 scenarios blocked, all gates/WP4 open. Await the next bounded safety/access decision.

Native008 attempt (2026-10-09): preflight blocker and all20 outcomes (private historical evidence; not published). All C01-C20 BLOCKED/not started: existing populated-checkpoint restore conflicts with the current no-real-working-data boundary, and Docker read access is denied.0 native executions/0 product tests rerun; no code/SQL/resource/service changes. Previous evidence is historical; all source/restore/default/runtime/full-WP4 gates remain open. Await owner data-scope decision and environment access before resuming.

Step008 runner implementation (2026-10-09): native-runner and transport evidence (private historical evidence; not published) implements26 fresh future subfixtures for20 planned groups.52 new plus224 unchanged selected tests pass (276 total); no native rehearsal/Docker/SQL/service operation executed. All full requirements and source/restore/default/runtime gates remain open. Next only a separately authorized fresh CLOSED-only native008 rehearsal; stop after implementation. Earlier dated preparation statements below are historical.

Step008 offline evidence (2026-10-09): continuous-custody foundation (private historical evidence; not published) adds49 synthetic checks and175 unchanged regressions (224 passed) for bounded AC-18/AC-22/AC-23 preparation. Typed identity/time/inventory/close/drain and20 fixture shapes are verified offline only. All20 native scenarios remain planned; source/restore/default-privilege/admitted-business/runtime/full WP4 gates remain open. No acceptance criterion is complete. Next owner-authorized native runner implementation/transport tests only; stop before native execution.

Step008 design evidence (2026-10-09): continuous-custody contract (private historical evidence; not published) and20 planned native fixture groups document bounded AC-18/AC-22/AC-23 preparation only. No native008 assertion, admitted business drain, source fence, restored-writer admission or future-default privilege policy has been verified by this stage. No acceptance criterion or WP4 is marked complete. Next separately authorized CLOSED-only offline foundation; stop before native work.

Current clone007 actual-login implementation (2026-10-08): private historical evidence (not published) supersedes preparation inventories below for bounded AC-18/AC-22/AC-23 evidence.363 selected offline checks pass. Native claims require completed fresh receipts and final preservation/owned cleanup; no complete acceptance criterion/WP4/runtime/main-rollout claim. Exact allowed grants are14 schema USAGE/52 function EXECUTEs while old entries/metadata/data stay fixed.

Clone007 offline foundation (2026-10-08): private historical evidence (not published) records partial AC-18/AC-22/AC-23 implementation evidence: separate CLOSED SQL/pure exact auth builders/48 new+279 existing offline checks. No PostgreSQL syntax/install/LOGIN/physical custody/ACL/native preservation proof; all24 actual-login scenarios remain planned, no acceptance criterion closed. Existing001–006/runtime/main unchanged; earlier design-only inventory is historical.

Authenticated CLOSED-controller design (2026-10-08): private historical evidence (not published) and its JSON checklist document bounded AC-18/AC-22/AC-23 planning for additive clone007, actual SCRAM sessions/least-privilege roles/physical custody/deny-only business probes/rollback and preservation. All24 new native scenarios remain planned/not run; no SQL/LOGIN/harness/credential/live action or acceptance completion. Prior006 bootstrap/SET ROLE evidence is not authenticated application custody, continuous fencing or runtime admission.

Clone006 verified (2026-10-08): private historical evidence (not published) adds bounded AC-18/AC-22/AC-23 native fourth-fresh-target evidence:49 exact same-OID CLOSED caps/52 bindings/14 roles/reached full-body rollback/ACL-definition drift denials/104 NULL-nonNULL probes/all52 actual55P03 latch timeouts/31-table preservation;279 units pass. Main20/M02/idle n8n preserved, new container/network removed and volume retained. SET LOCAL ROLE is not authenticated application LOGIN; no continuous-session/restore/future-default/runtime or complete acceptance gate inferred. Earlier preparation below is historical.

Clone006 preparation (2026-10-08): private historical evidence (not published) adds bounded AC-18/AC-22/AC-23 implementation/offline evidence for49 static deny-only caps/52 bindings/14 roles/private guard/receipt and276 unit/mock passes. Actual SQL/ACL/lock/rollback/31-table preservation planned/not run; four original services stopped/startup permission pending. No fresh main/M02/n8n recertification, authenticated app/continuous/restore/runtime or acceptance gate completion inferred.

Clone005 custody evidence (2026-10-07): private historical evidence (not published) adds bounded AC-18/AC-22/AC-23 preparation through second fresh001–005/inventory native connection-bound claim/owned-close/five exact NOLOGIN APIs/raw004-close denial/actual owner loss/no takeover/original reconciliation and all31-table preservation;249 units pass. Main/M02/n8n unchanged, all volumes/history retained. No whole14-scenario coverage, authenticated application custody/continuous business fence/PID-race safety/49 caps/old-session/restore/runtime or complete acceptance gate inferred.

Custody/coverage contract (2026-10-07): private historical evidence (not published) adds documented AC-18/AC-22/AC-23 preparation:49 SQL entries/52 role bindings/server-derived connection identity/guard ordering/raw-old-route bypass and termination race boundaries.224 units and offline literal source projection pass;14 new native assertions remain planned. No actual custody/hook/effective native ACL/source recertification/continuous/application-session/restore/runtime or complete acceptance gate is inferred.

Session inventory evidence (2026-10-07): private historical evidence (not published) adds bounded AC-18/AC-22/AC-23 actual fresh-clone exact registration/unknown-same-label-other-database-prepared blockers/registered exits/stale no fallback and all31-table preservation.204 units pass; main/M02/n8n unchanged, volume/history retained. No continuous source fence, actual PID-reuse safety, real application-session drain/authenticated controller custody, writer/restore/runtime admission or completed acceptance gate is inferred.

CLOSED primitive evidence (2026-10-07): private historical evidence (not published) adds bounded AC-18/AC-22/AC-23 preparation through second fresh001–004 clone target/atomic role-schema rollback/controller-CAS/replay/actual canary backend exit/row-lock timeout-wait-drain and full31-table preservation;184 unit/mock checks pass. Main/M02/n8n unchanged. These are private control primitives, not hooks fencing business functions, real application-session drain, controller OS/TCP-crash/liveness/restore/runtime admission or a completed acceptance gate.

Closed-first admission design (2026-10-07): private historical evidence (not published) specifies continuous/controller/session/epoch/restore failure boundaries for AC-18/AC-22/AC-23 preparation.169 unit/mock checks include16 pure planned-contract tests;20 native failure scenarios remain not run. CLI success exits2/runtime BLOCKED. No actual SQL fence, controller crash/drain, source baseline recertification, application LOGIN/runtime admission or complete acceptance gate is inferred.

Populated store-preflight evidence (2026-10-07): private historical evidence (not published) strengthens bounded AC-18/AC-22/AC-23 preparation with a separate credential-free target/receipt/catalog/nine-NOLOGIN-role boundary,153 unit/mock checks and fresh-clone actual excess-EXECUTE/table/schema denial/reversal/all31-table preservation. Main/M02/idle n8n unchanged. Successful preflight explicitly denies start/execute; no application LOGIN/HTTP/n8n/continuous-session-epoch/restore admission or complete acceptance gate inferred.

Populated publication follow-up (2026-10-07): private historical evidence (not published) adds actual14-scenario fresh populated-clone evidence for bounded AC-18/AC-22/AC-23 preparation: committed visibility/rollback/exact export/replays/expiry-successor/unknown/stale/budget/dead-letter and all31 original facts/catalog/sequences preserved with exact fixture deltas.131 units pass, main/M02/idle n8n preserved. No actual application LOGIN/HTTP/n8n/process-crash or general continuous/runtime/restore admission/full acceptance pass inferred; startup root cause remains open. Prior preparation blocker below is historical.

Populated publication preparation (2026-10-07): private historical evidence (not published) adds a closed fourteen-scenario committed publication/attempt/expiry/export suite and exact original-fact preservation checks;130 selected units pass. Native preflight blocked before clone creation by original PostgreSQL readiness, so no new SQL integration/current baseline/full AC-18/AC-22/AC-23 acceptance or admission pass is claimed.

Populated review slice (2026-10-07): private historical evidence (not published) records bounded AC-18/AC-22/AC-23 preparation with rollback-contained synthetic request/decision SQL checks after001–003;117 selected unit/mock checks pass. No committed approval/publication, actual LOGIN/HTTP, expiry-renewal/attempt/crash or full acceptance/admission evidence is inferred. Actual clone result is separately recorded in that report.

Populated clone003 evidence (2026-10-07): private historical evidence (not published) strengthens bounded AC-18/AC-22/AC-23 preparation via actual16 specific PUBLIC revocations, zero PUBLIC retail functions/nine exact NOLOGIN API sets, old restricted API calculation/read unchanged, rollback/immutable receipt/denials and31-table preservation.107 selected units pass. No app LOGIN/authentication/listener, main/M02 action or general runtime/restore admission; future function defaults/unexercised business paths remain open. No full acceptance/security/release gate inferred.

Populated clone002 evidence (2026-10-07): private historical evidence (not published) strengthens bounded AC-18/AC-22/AC-23 preparation: actual nine-table/49-function portal schema/contract ACL projection,21-table preservation, exact predecessor/rollback/receipt/replay/privilege denials on a fresh isolated clone;94 selected units pass. No UAT runtime grants copied, no owner action/main rollout/listener.16 inherited PUBLIC functions explicitly block application admission; populated business/HTTP/n8n/continuous admission/clean import/release gates remain open. No complete acceptance gate inferred.

Populated clone001 evidence (2026-10-07): private historical evidence (not published) adds bounded AC-18/AC-22/AC-23 preparation via actual separate main-only restore/all21-table preservation, transaction rollback and immutable committed deployment receipt/reconciliation, inert legacy compatibility and disabled copied identities.70 selected units pass; no actual lost TCP/crash, full portal bundle/025 behavior, main rollout/restored-writer admission/clean import or completed acceptance gate inferred.

Coordinated backup evidence (2026-10-07): private historical evidence (not published) adds actual common-window main/UAT/n8n capture, stable source fingerprints, fresh isolated complete row/catalog/sequence restoration, n8n home/key positive/negative checks and73 selected units. Original services/HTTP preserved, copied logins disabled and clocks/slots/history retained. Bounded recovery evidence strengthens AC-18/AC-22/AC-23/AC-24; no full release/restored-writer/populated-admission gate pass inferred.

Coordinated-checkpoint preparation (2026-10-07): private historical evidence (not published) defines exact private components and staged fencing/restore/admission checks. Eighteen synthetic metadata units do not prove a real capture, ACL/custody, coordinated restore, single writer or populated deployment. Docker Engine unavailable/no SQL today; no AC-18/AC-22/AC-23/AC-24 release gate closed.

Native happy-path checkpoint (2026-10-06): private historical evidence (not published) adds owner-supplied published-index/download-open screenshots/reported logout and independently read-only-matched actual download4129-byte approved SHA. Completes bounded single-target native happy-path evidence only; not full AC-07/AC-11–AC-15/AC-18/AC-22/AC-24, independent native-cookie revocation, negative/cross-browser/security/main rollout/clean-instance/coordinated recovery/ten-case/release gates. No extra runtime tests or publication inferred.

Owner-bound manual pilot evidence (2026-10-06): private historical evidence (not published) adds bounded AC-11–AC-15/AC-18/AC-22/AC-24 evidence: actual native owner approval independently bound to committed SQL, one real n8n execution63 via restricted single-action HTTP worker, fresh reconciliation/one slot/one before-deadline publication and exact owner-only HTTP export/anonymous denial/logout. Normal success only, not new fault/restore/clean-instance evidence. Worker removed/distinct pilot inactive-unbound-null-plan, main unchanged. Owner-native publication/download QA, populated admission/coordinated recovery/broader pilot/release remain open; no full gate pass.

Owner-native/readiness follow-up (2026-10-06): private historical evidence (not published) adds owner-supplied sign-in/detail/raw contract-report inspection/reported logout and actual READ ONLY exact pending-request/deadline/effective-right/preservation checks. Bounded AC-11–AC-15/AC-22 preparation only; manual decision/receipt/publication/download, full cookie-revocation/security, clean import/coordinated rollout/pilot/release remain unverified. No approval is inferred from inspection.

Assembled synthetic UAT evidence (2026-10-06): private historical evidence (not published) strengthens bounded AC-11–AC-15/AC-22 preparation via actual owner-only loopback HTTP, exact startup rights, origin/cookie/CSRF/expiry/hash/confirmation denials, separate synthetic decision replay/unpublished receipt and owner-only restart. 77 distinct unit/mock and22 fresh legacy-default SQL/ASGI checks pass. No owner-native-browser/worker/n8n publication/main migration/coordinated restore/clean import/pilot or complete gate claimed; pending browser fixture untouched.

Deployment preparation (2026-10-06): private historical evidence (not published) records16 new unit/mock tests and actual read-only preservation of fixed runtime/main20/M02/idle n8n. Migration/role/order/restore fences are documented, not implemented admission or rollout evidence. It closes no AC-18/AC-22/AC-23/AC-24 release gate; synthetic assembled listener/browser, coordinated recovery, clean import and pilot remain open.

Isolated n8n restore evidence (2026-10-06): private historical evidence (not published) strengthens partial AC-18/AC-22/AC-23/AC-24 through142 public metadata table row fingerprints/sequence last values,16 restored home-file hashes, recovered key/config, real wrong-key denial and two canary HTTP/external-runner executions after process restart. Main/M02 unchanged. A database clone is not a clean sanitized-workflow import gate, editor/browser UAT, coordinated business-writer admission, secure/off-device custody or full release completion.

Isolated crash/business restore evidence (2026-10-06): private historical evidence (not published) adds partial AC-18/AC-20/AC-22/AC-23/AC-24 evidence through nine actual API/n8n/dedicated-PG interruption and independent-cluster retail-row restore scenarios, real sanitized export, original authority/budget/history, explicit restored-token quarantine and corrupt-dump rejection. Main/M02 unchanged. Not whole-application metadata/key/config recovery, clean n8n import/deployment/browser UAT or completed release gates.

Bounded durable n8n evidence (2026-10-06): private historical evidence (not published) adds partial AC-11–AC-18/AC-22/AC-24 evidence through15 actual manual n8n/private HTTP/synthetic SQL scenarios: genuine execution correlation, committed grant before effect, same-slot lost-ack replay, cross-rerun three-slot exhaustion, unknown/report/reconcile recovery, real Retry-After/lease waits, no operator grant and sanitized export. Controlled response substitutions are not lost TCP/process crash/backup-restore/browser/main or completed gates. Earlier028 evidence is unchanged and separately scoped.

Bounded attempt-API evidence (2026-10-06): private historical evidence (not published) adds partial AC-11–AC-18/AC-22 preparation for exact committed reservation/receipt/state, separate service/operator credentials, uncertain-ack reconciliation, fresh-instance count, stale grants, expiry/cap/busy/concurrency and fail-closed ASGI input. Actual SQL plus in-process ASGI/injected acknowledgement faults, not listening HTTP/TCP/API-process restart/n8n/restore/browser/main or a completed gate. Existing SQL process-exit evidence remains separately scoped.

Bounded migration029 evidence (2026-10-06): private historical evidence (not published) adds partial AC-16/AC-18/AC-22 SQL preparation: append-only attempts, committed three-slot budget across executions, unknown/permanent/exhausted state, authoritative recovery and actual separate SQL-worker process exits before/after commit. Not an HTTP/n8n crash/restart/restore or complete gate; actual n8n identity/backoff/cross-rerun integration and main deployment remain open.

Bounded migration028/n8n evidence (2026-10-06): private historical evidence (not published) adds partial AC-11–AC-19/AC-22/AC-24 preparation: approved-only exact acceptance, expiry/original-key/concurrency/commit faults, actual n8n/private HTTP/SQL reconciliation/retry/exhaustion and sanitized real export. 90 SQL/ASGI/unit tests, one VM policy suite and eight actual scenarios pass. Faults are injected, not TCP/process-crash/production outage evidence; no durable SQL attempts/dead-letter/cross-rerun budget, main deployment/browser/restore/clean-instance or completed release gate.

Bounded migration-027 evidence (2026-10-06): private historical evidence (not published) adds partial AC-15/AC-22 preparation for isolated owner sign-in/logout, absolute-hour/fresh-clock checks, rotation/revocation/CSRF, separated rights and commit-before-cookie/failure rollback. 22 actual SQL/ASGI +2 registry units +135 regressions pass. Unknown acknowledgement is simulated after real commit, not TCP/process-crash evidence; no main/M02/new-target browser deployment/full security audit or completed release gate.

Bounded migration-026 evidence (2026-10-05): private historical evidence (not published) records 25 new SQL/ASGI/boundary checks +110 regressions for AC-11/AC-12/AC-13/AC-14/AC-18/AC-20/AC-22 preparation: service transition/auth/input/commit/reconciliation, owner-only exact retired history/provenance and fresh forms. No actual lost-network/crash/socket/browser UAT or main deployment/complete release gate; acknowledgement loss is simulated after real commit, real M02 unchanged.

Bounded migration-025 evidence (2026-10-05): private historical evidence (not published) records 24 new isolated actual-login/SQL checks (one owner-form ASGI flow) plus 86 categorized regressions for exact bindings, fresh approval/expiry, atomic transition and legacy fences. This is partial AC-11/AC-12/AC-13/AC-14/AC-18/AC-20/AC-22 preparation, not a complete release gate, real legacy adoption, service transition HTTP/provenance UI, network/crash/browser or restore evidence. Main/M02 unchanged.

All implementation criteria begin **NOT RUN**. Store a run record with timestamp, source snapshot, commit, environment, command/procedure, expected result, observed result, and a sanitised evidence link. A passing mock is not evidence of a live integration.

</details>

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
