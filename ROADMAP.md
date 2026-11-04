# Release roadmap and work budgets

## Delivered scope and remaining work (4 November 2026)

The public portfolio is complete: P1 Human Approval, P2 native AI tools, P3 MCP,
P4 RAG, P5 engineering checks, and F1-F6 website sections. Source, MIT License,
six screenshots and demo video are published in the
[repository](https://github.com/Eugene156/retail-analytics-automation).
Local CI: 56 pytest tests passed; [hosted CI passed](https://github.com/Eugene156/retail-analytics-automation/actions/runs/41799269037).
See [README](README.md), [acceptance](ACCEPTANCE.md) and
[requirement status](docs/REQUIREMENTS_MATRIX.md) for the bounded delivered result.

Remaining limitations are fresh-machine deployment/recovery verification,
Postman GUI verification and fixed-IP allowlist reliability. External business
connectors, broader benchmarks, BI and laboratory technologies are not implied
by completion of this portfolio. No new work is authorized by this roadmap.

The budgets and v0.x stages below are the original planning baseline, not measured
hours, promises or additional release blockers. Native008/N1 checkpoints remain
historical, with their original blockers preserved; they are not P1-F6 status.

<details>
<summary>Historical checkpoints preceding the published portfolio scope</summary>

N1 Offline Implementation INCOMPLETE/BLOCKED (2026-10-10): drafts and remaining work (private historical evidence; not published).335 existing+17 new offline tests pass; storage verification and role/catalog/ACL/evidence/fence review findings remain open. Native entry/transport/seal deny; no native008 integration. Next only owner-resumed offline completion, not native N1/N2/N3. All gates/WP4 OPEN.

N1 readiness BLOCKED (2026-10-10): stop evidence (private historical evidence; not published). Missing fixture-only native materializer/transport/private capture-storage and native observation contract require a bounded offline implementation/review before retry. No N1 allocation/materialization/capture; N2/N3 not started.17 current integration tests pass; all native gates/WP4 OPEN.

I3 offline integration completed (2026-10-10): results and native limits (private historical evidence; not published).318 preserved+17 new tests pass; explicit008 fixture check, strict package/context/topology bindings and native target/scope plans, no resource/native execution. N1 readiness/materialization/capture, N2 restore and N3 rehearsal planned/not-run; separate permission per stage. All gates OPEN; STOP before N1.

I2 completed (2026-10-10): offline recipe/capture results (private historical evidence; not published),13 new +305 unchanged tests pass. Full public-row SQL/alias, guarded source020/reference029 lifecycle and capture plan reproduce offline; no native operation. I3/N1-N3 planned/not-run, all gates/WP4 OPEN. Stop before separately authorized I3.

I1 offline boundary completed (2026-10-09): results and remaining gates (private historical evidence; not published),14 new +291 unchanged tests pass. Contract/mapping/context/secret registry implemented; I2 recipe/capture lifecycle, I3 native binding/integration and N1-N3 remain planned/not-run. No SQL/Docker/native/credentials. Stop awaiting I2-only permission.

Safe native fixture design (2026-10-09): recommendation and acceptance plan (private historical evidence; not published), pending approval. I1 fixture contract/context/scanner → I2 reproducible materialization/capture implementation → I3 explicit008 integration → separately authorized N1 native build/capture → N2 restore/reproduction → N3 CLOSED-only008. Preserve001-007 SQL/legacy behavior, public bundle and291 existing tests; never synthesize native/source evidence. Each stage ends with checks/saved results/STOP. All gates remain open; next only owner-approved offline I1.

Safe checkpoint compatibility BLOCKED (2026-10-09): 001/002 predecessor conflict (private historical evidence; not published).003-only mapping cannot satisfy legacy001 UUID binding or002 non-revoked owner/policy/UAT-reference requirements. Owner's stop condition applied; no code/native changes. Next owner decision: distinct authority-free001/002 contract design, followed by separately authorized implementation/materialization; all gates remain open.

Safe public checkpoint preparation (2026-10-09): offline evidence and compatibility limits (private historical evidence; not published). Public physical rows, logical baseline, fresh inert service specifications and rebuilt M02 candidate prepared;291 offline tests pass. Native materialization, catalog/ACL/SQL API observations and explicit003/008 fixture compatibility remain blocked/planned; no restore/rehearsal or WP4 completion. Stop awaiting owner authorization for that bounded compatibility task.

Codex/Docker access proposal (2026-10-09): one-shot access and authority-free checkpoint proposal (private historical evidence; not published). Owner host Docker access succeeds; info/ps discrepancy unresolved. Four read-only fixed-context metadata commands proposed through per-command escalation after explicit confirmation, no permanent rules/security changes. Separate public-data fixture needs empty operational authority and reviewed legacy003 report compatibility; not built.0 escalations/native/resource/restore/product-test changes. All gates/WP4 remain open; stop for confirmation.

Native008 preparation diagnostics (2026-10-09): checkpoint and Docker findings (private historical evidence; not published). Public UCI lineage/integrity confirmed, but main dump also contains project authentication/session/request history; full confidentiality/copied-authority safety not certified. Context is local/correct, docker-users enabled, command token Low Integrity; sandbox restriction is the leading access hypothesis, requiring ordinary-terminal comparison. Runtime isolation/engine readiness remain unverified. No restore/rehearsal/config/elevation or product changes; all20 scenarios blocked, all gates/WP4 open. Await the next bounded safety/access decision.

Native008 attempt (2026-10-09): preflight blocker and all20 outcomes (private historical evidence; not published). All C01-C20 BLOCKED/not started: existing populated-checkpoint restore conflicts with the current no-real-working-data boundary, and Docker read access is denied.0 native executions/0 product tests rerun; no code/SQL/resource/service changes. Previous evidence is historical; all source/restore/default/runtime/full-WP4 gates remain open. Await owner data-scope decision and environment access before resuming.

Step008 runner implementation (2026-10-09): native-runner and transport evidence (private historical evidence; not published) implements26 fresh future subfixtures for20 planned groups.52 new plus224 unchanged selected tests pass (276 total); no native rehearsal/Docker/SQL/service operation executed. All full requirements and source/restore/default/runtime gates remain open. Next only a separately authorized fresh CLOSED-only native008 rehearsal; stop after implementation. Earlier dated preparation statements below are historical.

Step008 offline checkpoint (2026-10-09): CLOSED observation foundation (private historical evidence; not published) and49 new offline tests implemented;224 selected checks pass. This completes only the offline foundation: no008 native groups executed, no new SQL/native launcher/source operation, no continuous fence or writer admission.001–007 and the design plan remain unchanged. Next separately authorized native008 runner implementation/transport tests, then stop before native rehearsal execution. Older next-task inventories below are historical.

Step008 design checkpoint (2026-10-09): continuous-custody failure contract (private historical evidence; not published) and20 planned native fixture groups saved. This completes only the design stage after007; zero008 native executions or new SQL/harness. Source fencing/restore quarantine/future defaults/admitted business drain/OPEN/main/runtime/full WP4 remain blocked. Next separately authorized008 offline foundation; verify and stop before any native008 run. Older next-task inventories below are historical.

Current clone007 actual-login implementation (2026-10-08): exclusive fresh001–006/007 runner and363 selected offline tests implemented. Current native receipts/failure history/cleanup are tracked in private historical evidence (not published), superseding preparation inventories below. Next after this bounded verification is continuous-custody/restore-quarantine/future-default gate design, not main rollout/OPEN/working admission or full WP4 completion.

WP4 clone007 offline foundation (2026-10-08): separate additive SQL/pure16-principal SCRAM-HBA-client-transaction builders/48 new tests,327 selected checks pass; original001–006/runner unchanged. No native harness wired/SQL or authentication executed/LOGIN provisioned, all24 native scenarios planned and007 incomplete. Next exclusive fresh launcher/secret-safe bounded transport/assertions before a NEW001–006/007 native run; no main/OPEN/business writer. Evidence and remaining gates: private historical evidence (not published). Earlier design-only inventory below is historical.

WP4 authenticated CLOSED-controller design (2026-10-08): additive clone007 interface and24 planned actual-login assertions now documented; exact16 new principals/SCRAM loopback/direct scopes/private credential transport/own custody and original-latch-first ordering, no weakening001–006 or old-custody adoption. Design only, no native/authenticated runtime proof. Next separate clone007 implementation/harness with offline checks before a NEW001–006 native test; no OPEN/main rollout/business writer. Continuous/restore/future-default/runtime/full WP4 remain open. See private historical evidence (not published); earlier next-task statements below are historical.

WP4 clone006 verified (2026-10-08): fourth fresh1900d1fafd74 passes001–006/inventory/custody,49 same-OID deny-only caps/52 bindings/14 roles/full-body rollback/actual latch locks and all31-table preservation;279 units pass. Main/M02/idle n8n unchanged, new owned container/network removed/volume retained, third stopped target unverified. Next authenticated CLOSED-controller interface/actual-login denial test plan only, no implementation/OPEN/main rollout. Continuous/source-session/restore/future-default/runtime/full WP4 remain open; earlier preparation next steps below are historical. See private historical evidence (not published).

WP4 clone006 preparation (2026-10-08):49 static same-OID CLOSED-only caps/52 bindings/14 roles/private guard/receipt/fresh001–006 mode implemented;276 units pass. Native SQL/ACL/lock/31-table preservation blocked/not run: Linux engine available, four original containers stopped/startup permission pending. No service/main/M02/SQL/resource operation. Next authorized readiness/read-only baseline then one fresh006 run, no OPEN/runtime/full WP4 gate completion. See private historical evidence (not published); earlier next-task statements are historical.

WP4 clone005 custody (2026-10-07): second fresh001–005/inventory run and249 units pass physical-connection ownership/exact five APIs/old-close revocation/actual owner loss/no takeover/reconciliation/all31-table preservation. Main/M02/n8n unchanged, fifteen volumes/history retained/temporary containers-networks removed. First idle psql client-exit failure corrected in helper only. Next separate clone006 same-OID CLOSED-only caps for49 frozen SQL entries, not OPEN/admitted business execution. Authenticated app/continuous-old-session/PID-race/restore/future-default/runtime/full WP4 gates remain open. See private historical evidence (not published); earlier next-task statements are historical.

WP4 custody/coverage design (2026-10-07):49 frozen SQL entries/52 bindings/14 roles/19 mutators, physical-connection server identity/no takeover/old-close bypass closure and later same-OID CLOSED-only caps specified. Fixed source audit/224 units pass;14 new native assertions remain planned, no controller/SQL/hook/runtime/source action. Next only clone005 custody/reconciliation/denial/preservation probes, no business caps or OPEN. Effective rights/authenticated runtime/continuous-session-restore/future-default/full WP4 gates remain open. See private historical evidence (not published).

WP4 session inventory (2026-10-07): first exclusive new001–004 clone run passes exact own-backend registration/unknown-same-label-other-database-prepared blockers/three registered exits/stale identity no fallback, retaining ten observations/three original identities and all31 retail fingerprints/CLOSED state/catalog.204 units pass, main/M02/idle n8n unchanged, thirteen volumes/history retained and temporary container-network removed. Next specify server-derived controller custody/exact business-guard coverage and race limits; no continuous fence/application LOGIN/OPEN/restore/runtime or full WP4 gate inferred. See private historical evidence (not published).

WP4 CLOSED primitives follow-up (2026-10-07): second new populated001–004 clone verifies private CLOSED latch/controller generation/original-operation reconciliation, real backend exits/row-lock timeout-wait-drain, three committed control events and all31-table preservation.184 units pass; first SQL-NULL helper parsing failure fixed without SQL guard changes, failed/successful volumes retained. Main/M02/n8n unchanged. Next clone registered-backend inventory/quiescence and unknown/prepared blockers; no OPEN/application LOGIN/business-route enforcement or whole continuous/restore/runtime/full WP4 pass. See private historical evidence (not published).

WP4 closed-first controller design (2026-10-07): persistent CLOSED latch/exact controller generation/original-operation reconciliation/complete session-prepared-transaction drain and restored-xid quarantine specified;20 planned native failure assertions,169 passing unit/mock checks, no actual controller/native drill/admission. Next implement only closed latch/CAS/reconciliation/separate-session drain probes on a fresh populated clone, no OPEN function/application LOGIN/listener/main action. Whole continuous/session/epoch/restore/runtime/owner UAT/clean import/pilot/release remain later. See private historical evidence (not published).

WP4 store-preflight follow-up (2026-10-07): separate populated configuration/receipt/catalog/effective-right boundary and closed fresh-clone flag verified;153 unit/mock checks, five metadata denials, three real temporary ACL denials/all31-table preservation pass. Main/M02/idle n8n unchanged; no runtime/admission/listener/actual LOGIN. Next continuous maintenance/session/epoch controller failure-contract design, then separately reviewed implementation; restored-xid/custody/future defaults/business store/runtime/owner UAT/clean import/pilot/release remain open. See private historical evidence (not published); earlier next-task statements are historical.

WP4 populated publication follow-up (2026-10-07):14 actual SQL scenarios now pass on a fresh001–003/review main-only clone;5 synthetic publications/25 worker events/104 exact fixture rows retained and all original31 tables/catalog/sequences preserved.131 units pass. Source readiness returned and four original services/main/M02/idle n8n checks pass; startup cause remains unproved. Ninth volume/history retained, clone container/network removed. Next separate populated store/config validation and executable clone-only admission prerequisites; general runtime/continuous/restore admission and full WP4 remain open. See private historical evidence (not published); preceding preparation blocker is historical.

WP4 populated publication preparation (2026-10-07): closed fourteen-scenario clone suite/fixture partition preservation implemented;130 units pass. Native execution blocked before clone creation by stopped original services/PostgreSQL startup readiness1 after starting existing PG. Next readiness/main/M02/idle-n8n READ ONLY checks, then original runtime resume and fresh suite. No actual new committed publication/attempt/integration or admission completion. See private historical evidence (not published).

WP4 populated review slice (2026-10-07): rollback-contained synthetic issuance/review/hash-CSRF-conflict/TTL-boundary checks added after fresh001–003, with full31-table preservation required.117 selected units pass. This is not committed publication/attempt/recovery or runtime admission; main/M02 stays observation-only. Current integration evidence and next bounded task: private historical evidence (not published).

WP4 deployment003 (2026-10-07): clone-only exact16 PUBLIC EXECUTE removals/zero PUBLIC functions, nine exact NOLOGIN API sets, unchanged old restricted report calculation/read, atomic rollback/receipt/denials and31-table preservation verified;107 selected units pass. Main/M02/idle inactive n8n unchanged; new volume/history retained, owned container/network removed. Next populated synthetic SQL business regressions with separate fixture deltas; no runtime/admission/full WP4/release pass. Future default-privilege and continuous/session/restore gates remain open. See private historical evidence (not published).

WP4 deployment002 (2026-10-07): populated clone-only nine-table/49-function final portal schema, contract ACL reference projection,21-table preservation and transaction/privilege checks verified;94 selected units pass. Main/M02 unchanged, all roles NOLOGIN/no runtime admission. Four new volumes/evidence retained. Next clone-only003 hardening of16 historical PUBLIC functions, then remaining continuous admission/runtime/business regression/import/pilot/release gates; full WP4 remains open. See private historical evidence (not published); prior dated next-action statements below are historical.

WP4 current implementation (2026-10-07): deployment001 separately authored/verified on a new populated main-only clone, preserving21 original tables/catalog/sequences and immutable history; SQL guard/rollback/receipt/replay/inert-legacy checks passed,70 selected units. Main remains20/M02 unchanged, no listener/writer grant. Next deployment002 final portal schema/dependency/equivalence rehearsal on a new clone, not live rollout. Continuous admission/live runtime/clean import/broader pilot/release remain open. See private historical evidence (not published); earlier design-only statements below retain their date/scope.

WP4 current follow-up (2026-10-07): coordinated capture/isolated restore is verified in private historical evidence (not published). Populated deployment design now selects separate additive SQL/ledger, main-only clone rehearsal and eventual in-place rollout; original guards/M02 unchanged.35 selected unit/mock checks passed, no live operations this increment. Next clone-only deployment001 legacy compatibility and executable guard/preservation rehearsal; continuous writer/admission, populated portal bundle/runtime, clean import/broader pilot/release remain open. See private historical evidence (not published). Earlier unavailable-engine/unimplemented-capture statements below are historical.

WP4 coordinated-checkpoint checkpoint (2026-10-07): gap assessment and six ordered gates documented; pure ten-component manifest structure18 synthetic tests passed, actual capture/fencing/admission not implemented. Docker Engine unreachable blocks fresh inventory/backup. Next Engine running/read-only source/mount/space inventory, then scoped fence/capture runner before any populated mutation. Native published happy path stays complete; no replay/full WP4/release/ETA inferred. See private historical evidence (not published).

WP4 native happy-path checkpoint (2026-10-06): owner published-index/download-open screenshots and reported logout, independently matched actual Downloads JSON4129-byte SHA. Single synthetic sign-in/approval/publication/download/open/logout happy path complete, not full UAT/ten-case/main rollout/WP4/release. Next bounded read-only populated migration/admission gap assessment with coordinated backup/single-writer requirements before any deployment. No new execution/migration/renewal/ETA; see private historical evidence (not published).

WP4 owner-bound pilot checkpoint (2026-10-06): one actual owner-approved synthetic n8n execution63/server acceptance before original expiry and exact automated owner export verified. Single-action worker stopped/removed, separate pilot inactive/unbound/null-plan; main/M02 unchanged. Next native published-page/download/logout QA. Populated migrations/admission/coordinated restore/clean-instance import/broader pilot/release still open; no completion/ETA/savings claim. See private historical evidence (not published).

WP4 owner-native/readiness checkpoint (2026-10-06): supplied screenshot/expanded contract-report/reported logout cover native inspection only. READ ONLY readiness verifies exact pending synthetic binding/original deadline/effective rights and preserves main/M02; no worker/approval/n8n execution. Next owner's confirmed synthetic decision, then one-action separately identified manual pilot preparation/execution and receipt/download UAT. Populated deployment/coordinated restore/clean import/release remain open; see private historical evidence (not published).

WP4 checkpoint (2026-10-06): assembled synthetic owner18082/startup privilege/HTTP/restart checks passed, browser fixture pending/no worker or publication. 77 distinct unit/mock +22 actual legacy-default SQL/ASGI regressions; main20/M02 unchanged. Next owner-browser sign-in/report/contract inspection/logout (no approval yet), then explicitly bound synthetic manual-worker pilot preparation. Populated migration/admission/coordinated restore/clean import/release still open. See private historical evidence (not published); no completion/ETA claim.

WP4 checkpoint (2026-10-06): bounded deployment preflight/runbook completed:16 unit/mock checks and actual read-only runtime/main/n8n observations pass, activation explicitly BLOCKED. Next isolated synthetic owner/worker UAT runtime with per-port strict origin and startup privilege/unused-login fences, then native-browser UAT. Main-specific migration/admission, coordinated backup/single-writer recovery, clean import/pilot/release remain open; no WP4 completion/ETA. See private historical evidence (not published).

WP4 checkpoint (2026-10-06): isolated n8n metadata/key/config/home restoration passed all142 table fingerprints/sequence values,16 file hashes, missing/wrong-key fences and two authenticated canary external-runner executions. Next bounded deployment preflight/runbook for new-target runtime/roles/migration order/restore admission, before rollout/owner browser UAT/pilot. Main/M02/legacy dispatch unchanged; whole-project recovery/custody and WP4 completion not claimed. See private historical evidence (not published).

WP4 checkpoint (2026-10-06): nine actual isolated crash/business-restore scenarios passed with original authority, durable budget/history and single effects preserved. Next isolated n8n metadata/encryption-key/config restoration, with old writers fenced before copied-action admission; then bounded deployment/owner browser UAT and pilot/release. Main/M02/legacy dispatch untouched, no WP4 completion or measured ETA. See private historical evidence (not published).

WP4 checkpoint (2026-10-06): separate inactive durable n8n v2 passed15 actual private HTTP/SQL scenarios and real sanitized export roundtrip. Actual execution IDs and original keys, committed three-slot budget across four reruns, acknowledgement loss/reconciliation/lease/backoff verified; main/M02 and old workflow untouched. Next isolated interruption/restart/backup-restore recovery, then bounded deployment/owner browser UAT and pilot/release. No WP4 completion or measured ETA. See private historical evidence (not published).

WP4 checkpoint (2026-10-06): isolated commit-safe attempt worker/operator API wraps unchanged029 with exact validated projection and acknowledgement-only grant/receipt, no auto retry/reset/renewal. Next inactive actual n8n integration with real execution identity, bounded committed slots across reruns, loss/recovery/backoff/export; main deployment/browser/restore/pilot remain later. No WP4 completion or measured ETA. See private historical evidence (not published).

WP4 checkpoint (2026-10-06): migration029 isolated durable worker SQL foundation records attempts/unknown/dead-letter/exhaustion and explicit bounded operator reconciliation without resetting committed slots or extending expiry. Actual SQL-worker process exits are covered; HTTP/n8n integration remains next, then main deployment/browser/restore/pilot. No WP4 completion or measured ETA. See private historical evidence (not published).

WP4 checkpoint (2026-10-06): isolated manual n8n outbox acceptance/reconciliation passed 90 SQL/ASGI/unit tests, one VM suite and eight real n8n/private HTTP/synthetic SQL scenarios. Main/M02 untouched, no auto approval/renewal. Next durable worker attempts/unknown/exhaustion/operator audit across reruns/restarts; deployment/browser UAT/restore/pilot remain later. See private historical evidence (not published); no WP4 completion or measured ETA.

WP4 checkpoint (2026-10-06): isolated new-target login/logout lifecycle passed 22 SQL/ASGI +2 registry units +135 regressions; main/M02 unchanged. Next bounded increment is isolated manual-only n8n outbox orchestration with fixed worker rights/original-key reconciliation, not automatic approval or renewal. Deployment/browser UAT/failure/restart/restore/pilot remain later. Evidence: private historical evidence (not published); no WP4 completion or measured ETA.

WP4 checkpoint (2026-10-05): isolated service transition API and owner provenance/retired-history presentation passed 25 new +110 regressions. Next bounded increment is isolated login/logout/session integration; n8n outbox worker and deployment/restart/restore/browser UAT remain later. Main/M02 unchanged, old approved/uncertain effects still blocked. See private historical evidence (not published); no WP4 completion or measured-hour estimate.

WP4 checkpoint (2026-10-05): isolated migration 025's explicit expired-unreviewed legacy transition passed 24 new checks plus 86 regressions; real main/runtime unchanged. Next bounded increment is authenticated service transition API and owner-visible provenance/retired-legacy presentation, then login/logout, n8n outbox worker and deployment/restart/restore/browser UAT. Old approved/uncertain effects need separate reconciliation. Evidence: private historical evidence (not published); this does not close WP4 or add a measured hour estimate.

These are proposed scope-control budgets, not measured estimates or calendar promises. The owner has not supplied a daily schedule or start date. Enter those in STATUS.md after G0. Track focused human/project hours separately from unattended downloads and model runtime.

</details>

## G0: maximum 8 focused hours

1. Host, Git, Docker and storage checks: up to 2 hours.
2. Complete archive import/profiling and provenance: up to 2 hours.
3. Minimal service connectivity, model trials and pins: up to 3 hours.
4. Evidence review and scope/resource decision: up to 1 hour.

A missing installer/login can block a check; it does not justify pretending that the environment is ready. Complete independent checks, then document the actual blocker.

## v0.1: maximum 40 focused hours after G0

| Work package | Budget | Observable output |
| --- | ---: | --- |
| WP1: Business baseline, data/KPI contracts and initial BPMN | 5 h | Manual task definition, checked examples and process files |
| WP2: Core deployment, import, quality checks and SQL | 10 h | Reproducible deterministic report |
| WP3: n8n triggers/sub-workflows and local AI commentary | 6 h | Validated commentary or explicit safe fallback |
| WP4: Review, approval, outbox, local publication and audit | 8 h | Successful and rejected/expired cases |
| WP5: Failure tests, restart and basic restore | 5 h | Acceptance evidence and documented recovery |
| WP6: Three-way pilot, README, screenshots and demo | 6 h | Ten-case pilot and honest first release |
| **Total** | **40 h** | **A complete scoped reporting process** |

Checkpoint after each package. At 20 hours, confirm that a deterministic report works. At 32 hours, freeze optional features and prioritise acceptance/evidence. If the original scope will not fit, reduce the number of KPIs, report formats, connectors and UI polish first. Do not remove arithmetic correctness, identity checks, duplicate protection, minimum failure tests or honest status reporting. A reduced release must name deferred acceptance items.

## v0.1+ and v0.2: individually bounded increments

These budgets are admission caps for the next iteration, not extra mandatory work before publishing v0.1. Re-estimate after actual v0.1 evidence.

| Increment | Initial cap | Exit evidence |
| --- | ---: | --- |
| Importable English demo workflow | 6 h | Clean n8n URL import; zero-credential basic path; reduced-scope disclosure |
| GitHub + Telegram connectors and OAuth increment | 12 h | Real authorized API calls, revocation/reconnect and failure recovery |
| Native n8n agent + own/external MCP | 12 h | Actual tool selection/calls, bounded state and security tests |
| pgvector RAG and local evaluation | 14 h | Provenance, update/delete, held-out questions and baseline comparison |
| BI, dbt/Pandera/DuckDB and broader measurement | 14 h | Verified dashboard, distinct data checks and quality-adjusted results |

## v0.3 operational experiments

Choose only an experiment justified by measured behavior: queue/worker recovery; observability/alerts; process mining of our own execution log; broader analytics/segmentation. Assign one question, one baseline and an initial 4–8 hour investigation cap. The cap buys a measured decision, not a promise of a finished integration.

## v0.4 technology breadth

LangGraph, A2A, Skills, Qdrant comparison, reranking, GraphRAG, document parsing/OCR, Langfuse, alternate caches/storage and IAM/OPA remain visible in the technology roadmap. Each needs a runnable demonstration and documented result before being called implemented. A no-benefit result may close an experiment without adding that component to the default product.

## No uncontrolled expansion

Do not add another platform solely to increase the container count. The roadmap preserves the owner's broad learning/portfolio goal while requiring an explanation, measurable question, limited resources and evidence for every addition.
