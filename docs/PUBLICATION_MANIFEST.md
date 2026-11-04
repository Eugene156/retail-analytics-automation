# Publication selection manifest

Status: proposed file set; nothing staged or published. Documentation refreshed
on 4 November 2026. The original selection had 461 untracked candidates; the
manifest, owner-approved LICENSE, six reviewed screenshots and optimized video
add nine PUBLIC files. Counts include these approved additions, the explicit final selection correction below, not an inventory of other later files. No file is
moved/deleted. PRIVATE and REVIEW paths are ignored as a staging safety barrier.

## Selection policy

PUBLIC contains application/API/UI source, SQL migrations, portable tooling/tests,
sanitized P1-P4/F2 workflow templates, reviewed evidence, public API artifacts and
selected portfolio documentation. The exact inventory below is authoritative;
directory membership alone is not permission to add future files.

PRIVATE contains owner handoffs, access/recovery/setup instructions and agent
prompts. Existing .local/, credentials/, secrets/, models/, volumes/, data/raw/,
data/processed/, dumps/, sessions/, execution history, backups and logs remain
excluded. Never add encrypted backups, recovery keys, filled environments or raw
n8n execution/credential exports. Workflow credential IDs are references, not
portable credentials; initialize fresh local authority separately.

REVIEW files are withheld, not declared unsafe: historical operational design,
legacy fixtures/workflows, machine-specific deployment/recovery helpers, image
pins and dependency/version/license inventories. Compose files and working paths
are unchanged. Do not use git add -f to bypass their review status.

## Required release decisions

- README now covers F1-F6, controlled F2 actions, historical AI evidence, local
  navigation and verified/unverified boundaries. Its Mermaid section is the public
  architecture overview. Legacy ARCHITECTURE.md remains REVIEW and is not linked;
  no exception is needed merely to publish an architecture diagram.
- SHA256SUMS needs scope/freshness review before any inclusion.
- Owner approved MIT for original material: LICENSE carries copyright (c) 2026
  Eugene156. THIRD_PARTY_NOTICES.md separates dataset/software/model rights and
  describes actual data transformations. No runtime/model/raw-data redistribution
  is intended; uncertain external snippets require explicit provenance review.
- demo/*.yaml and g0/ need portability/image-build review. Local execution by a
  reviewer is optional; do not claim a fresh-machine bootstrap was verified.
- Confirm whether legacy operational docs/helpers are useful portfolio material.
  Before releasing excluded runtime files or helper-dependent tests, check imports
  and fixture references; this selection does not prove a clean checkout passes.
- New F3-F6 UI tests exist but the hosted CI list still contains the earlier six
  modules. Extending release checks requires a separate change.
- Six reviewed screenshots and the exact optimized MP4 are selected below after
  owner-authorized representative frame review. Private review frames remain excluded.
- Run release static/selected CI checks against the final selected checkout before
  committing. This manifest is not a commit instruction or a CI PASS claim.
- Later files, including tests/test_portal_presentation.py, need explicit selection
  review before inclusion. The snapshot counts below do not authorize new paths.

## Remaining REVIEW groups and minimum exceptions

All 141 original REVIEW files remain withheld; 21 additional legacy
files are now withheld as listed in the final selection correction. Group counts come from the existing
selection inventory; this documentation task does not approve or unignore them.

| Group | Count | Release recommendation |
| --- | ---: | --- |
| Historical architecture and checksum roots | 2 | Keep withheld; README supplies the public architecture. Rebuild checksums only for a finalized file set. |
| Operational/legacy design and milestone documents | 86 | Keep withheld; existing public API/evaluation/business documents cover the portfolio narrative. |
| Demo Compose configurations | 3 | Review only if owner opts into reproducible installation. Validate host paths, image/build inputs, secrets and license notices first. |
| G0 prototype/runtime files | 5 | Keep withheld unless a demonstrated build or selected-test dependency requires a specific file. |
| Operational, recovery and rehearsal helpers | 22 | Keep withheld; grant an exception only for a proven public-source or selected-CI dependency after focused privacy review. |
| Helper-dependent tests | 18 | Keep paired with their withheld helpers; do not publish tests that require missing private/review fixtures. |
| Version inventories | 2 | Review only when needed to pin an approved reproducible setup. |
| Legacy workflow/attempt-policy files | 3 | Keep withheld; current sanitized public workflows cover the showcase. |

**Essential exceptions recommended now: none.** Local installation is optional for
portfolio review. Before staging, verify selected-CI imports and fixture references
in a clean selected checkout. If it exposes a missing dependency, propose that
specific file for review rather than promoting a whole directory. Publication authorization remains separate; no PRIVATE path is eligible for an exception.

Runtime/source exceptions identified by focused import review are withheld
together with their dependent helpers/tests; no source or working paths changed.

## Media review (4 November 2026)

Six PNGs selected under media/ show the intended F1-F6 pages. Each was decoded,
visually inspected in full, and checked for visible credentials/private information.
No such issues were observed. Files retain their supplied names and bytes; the
originals and all private review material remain excluded.

The supplied optimized MP4 is 4,176,496 bytes (3.98 MiB), 111.367 seconds,
1918 x 1056, H.264/avc1, with no audio track. Its MP4 boxes parse correctly and
moov precedes mdat. This meets GitHub's repository file-size limits; hosted
playback has not been tested. No original large videos, ZIPs or duplicates were
present among the seven supplied top-level files.

**Video approved for the local release candidate:** owner-reported independent
review used 37 distinct frames extracted sequentially at 3-second intervals across
the complete 111-second recording. All six portfolio sections were visible; no
passwords or authentication tokens were identified in the sampled frames. Demo
request IDs and report hashes were visible and accepted by the owner. Coverage is
representative sampling, not exhaustive frame-by-frame verification. The earlier
repeated-opening-frame extraction was a sampling-method failure, not evidence that
the recording was static. That unsuccessful method was not rerun.

The selected exact path is
`media/Retail_Analytics_Automation_Demo_GitHub.mp4`. Its SHA-256 is
`babed20da7a6bad6551444704ec256d2891f37b1d3bb430f66dd01cede404941`. The public copy matches the private original byte-for-byte.
No media was edited, regenerated or transcoded. Original videos, archives and
private extraction images are not publication assets. Inclusion does not authorize
Git staging, committing, uploading or publishing.

## Final selection correction (4 November 2026)

Owner approved tests/test_portal_presentation.py as PUBLIC. It retains current F2
rendering/form/security regressions. It is not added to portable CI because its
FastAPI/psycopg dependencies are outside the existing lightweight CI environment;
its prior focused checks remain separate evidence.

Two obsolete JS helpers containing private machine paths, the admission-contract,
custody-foundation and deployment-preflight groups, and their dependent legacy
helpers/tests are now REVIEW/excluded. The legacy attempt-workflow builder and
safe-checkpoint groups also required withheld inputs and are excluded with their
dependents. Exact moved paths appear in the REVIEW inventory below; originals
remain on disk. No application module or configured CI test was removed.

The six configured CI test modules and their Python imports remain in PUBLIC;
CI commands and meaningful coverage are unchanged. Their existing offline evidence
is distinct from a hosted GitHub run. pytest and PyYAML are unavailable in the
current host runtime, so full configured CI cannot be rerun without an approved
environment containing them. No packages were installed.

## Counts

- PUBLIC: 296
- PRIVATE: 13
- REVIEW: 162

<details>
<summary>PUBLIC — exact paths (296)</summary>

```text
.env.example
.gitattributes
.github/workflows/ci.yml
.gitignore
ACCEPTANCE.md
LICENSE
README.md
ROADMAP.md
SPEC.md
THIRD_PARTY_NOTICES.md
api/__init__.py
api/f2_assets/f2.css
api/f2_assets/f2.js
api/f2_assets/index.html
api/f2_creation.py
api/local_publication.py
api/main.py
api/observability.py
api/overview.py
api/overview_assets/index.html
api/overview_assets/overview.css
api/overview_assets/overview.js
api/p12_demo.py
api/p2_demo.py
api/populated_deployment.py
api/portal.py
api/portal_attempts.py
api/portal_auth_v2.py
api/portal_publication.py
api/portal_review_v3.py
api/portal_transition_v1.py
api/portal_uat.py
api/portal_worker_v2.py
api/preview.py
api/publication_dispatch.py
api/reviewer.py
config/ci-requirements.txt
db/demo/f2_creation.sql
db/demo/p12_report_binding.sql
db/deployment/001_legacy_compatibility_rehearsal.sql
db/deployment/002_portal_schema_rehearsal.sql
db/deployment/003_acl_hardening_rehearsal.sql
db/deployment/004_closed_control_rehearsal.sql
db/deployment/005_controller_custody_rehearsal.sql
db/deployment/006_business_guard_manifest.json
db/deployment/006_business_guard_rehearsal.sql
db/deployment/007_authenticated_closed_rehearsal.sql
db/import_finalize.sql
db/migrations/001_source_ingest.sql
db/migrations/002_policy_v1_classification.sql
db/migrations/003_safe_parse_execution.sql
db/migrations/004_period_kpis_v1.sql
db/migrations/005_sale_invoice_consistency.sql
db/migrations/006_overlap_policy_v1.sql
db/migrations/007_overlap_domain_guard.sql
db/migrations/008_canonical_period_kpis_v1.sql
db/migrations/009_canonical_period_kpis_asof_v1.sql
db/migrations/010_deterministic_period_report_v1.sql
db/migrations/011_deterministic_comparison_report_v1.sql
db/migrations/012_comparison_api_boundary.sql
db/migrations/013_report_requests.sql
db/migrations/014_report_identity_constraints.sql
db/migrations/015_immutable_approval_proposals.sql
db/migrations/016_owner_read_auth.sql
db/migrations/017_explicit_approval_requests.sql
db/migrations/018_owner_portal_sessions.sql
db/migrations/019_decision_outbox_foundation.sql
db/migrations/020_portal_decision_projection.sql
db/migrations/021_publication_dispatch_ledger.sql
db/migrations/022_portal_publication_foundation.sql
db/migrations/023_portal_publication_reads.sql
db/migrations/024_portal_review_projections.sql
db/migrations/025_portal_legacy_transition.sql
db/migrations/026_portal_transition_reads.sql
db/migrations/027_portal_auth_v2.sql
db/migrations/028_portal_worker_boundary.sql
db/migrations/029_portal_worker_attempts.sql
db/tests/001_source_ingest.sql
db/tests/002_import_finalize_setup.sql
db/tests/003_conflicting_replay_setup.sql
db/tests/004_classify_policy_v1.sql
db/tests/005_classification_conflict.sql
db/tests/006_safe_parsers.sql
db/tests/007_overlap_policy_v1.sql
db/tests/008_canonical_period_kpis_v1.sql
db/tests/009_canonical_period_kpis_asof_v1.sql
db/tests/010_deterministic_period_report_v1.sql
db/tests/011_deterministic_comparison_report_v1.sql
db/tests/011_real_comparison_smoke.sql
db/tests/012_comparison_api_boundary.sql
db/tests/013_report_requests.sql
db/tests/015_immutable_approval_proposals.sql
db/tests/015_proposal_atomicity.sql
db/tests/016_owner_read_auth.sql
db/tests/017_explicit_approval_requests.sql
db/tests/017_request_atomicity.sql
db/tests/017_request_binding_negatives.sql
db/tests/018_owner_portal_sessions.sql
db/tests/019_decision_outbox_foundation.sql
db/tests/020_portal_decision_projection.sql
demo/p4_documents.json
demo/p4_schema.sql
docs/AI_EVALUATION.md
docs/AI_EVALUATION_REPORT.md
docs/API_DEMO_GUIDE.md
docs/BUSINESS_ANALYSIS.md
docs/DATA_CONTRACT.md
docs/DEMO_AND_GITHUB.md
docs/DEMO_VIDEO_CHECKLIST.md
docs/G0_DATA_PROFILE.md
docs/KPI_DICTIONARY.md
docs/MEASUREMENT.md
docs/N8N_COVERAGE.md
docs/PUBLICATION_MANIFEST.md
docs/REQUIREMENTS_MATRIX.md
docs/SOURCES.md
docs/TECHNOLOGY_ROADMAP.md
docs/WP1_AS_IS.bpmn
docs/WP1_GOLDEN_CASES.md
docs/WP1_MANUAL_BASELINE.md
docs/WP1_PROCESS_MODELS.md
docs/WP1_TO_BE.bpmn
docs/WP2_CANONICAL_KPIS.md
docs/openapi_demo.json
docs/postman_collection.json
docs/postman_environment.template.json
evidence/README.md
evidence/p12_human_approval.json
evidence/p1_report_demo.json
evidence/p2_ai_agent.json
evidence/p2_runtime_probe.json
evidence/p3_mcp_agent.json
evidence/p3_mcp_discovery.json
evidence/p4_preflight.json
evidence/p4_rag_runtime.json
evidence/p6_combined_repair.json
evidence/p6_live_validation.json
evidence/templates/acceptance-run.json
evidence/templates/manual_report.md
evidence/templates/measurement.csv
media/01-overview.png
media/02-human-approval.png
media/03-ai-agent.png
media/04-mcp-analytics.png
media/05-knowledge-assistant.png
media/06-api-ci.png
media/Retail_Analytics_Automation_Demo_GitHub.mp4
scripts/check-prerequisites.ps1
scripts/check-prerequisites.sh
scripts/check_p12_demo.py
scripts/check_p2_demo.py
scripts/check_p3_demo.py
scripts/check_p4_demo.py
scripts/check_publication.py
scripts/check_wp1_fixture.py
scripts/check_wp1_manual_cases.py
scripts/check_wp2_api_live.py
scripts/check_wp2_canonical_workbook.py
scripts/check_wp2_cases_live.py
scripts/check_wp3_n8n_faults.py
scripts/check_wp3_preview_live.py
scripts/check_wp4_decisions_local.py
scripts/check_wp4_dispatch_local.py
scripts/check_wp4_dispatch_native.py
scripts/check_wp4_n8n_publication_local.py
scripts/check_wp4_portal_publication_local.py
scripts/check_wp4_proposals_live.py
scripts/check_wp4_requests_v2_live.py
scripts/docker_archive.py
scripts/evaluate_ai_demo.py
scripts/evaluate_g0_commentary.py
scripts/g0_bootstrap.py
scripts/g0_concurrent_probe.py
scripts/g0_import_credential.py
scripts/g0_import_stress.py
scripts/g0_verify.py
scripts/p12_demo.py
scripts/p12_token_repair.py
scripts/p1_demo.py
scripts/p2_demo.py
scripts/p2_tool_call_probe.py
scripts/p3_demo.py
scripts/p3_mcp_server.js
scripts/p4_demo.py
scripts/p4_workflows.py
scripts/profile_online_retail_ii.py
scripts/read_tool_answer.py
scripts/test_p4_answer_guard.py
scripts/test_wp2_period_kpis.py
scripts/validate-wp1-bpmn.ps1
scripts/wp2_api_local.py
scripts/wp2_import_workbook.py
scripts/wp3_n8n_local.py
scripts/wp3_preview_local.py
scripts/wp4_checkpoint_manifest.py
scripts/wp4_custody_coverage_contract.py
scripts/wp4_dispatch_ipc.py
scripts/wp4_n8n_restore_snapshot.py
scripts/wp4_portal_local.py
scripts/wp4_recovery_storage.py
scripts/wp4_reviewer_local.py
scripts/wp4_safe_fixture_contract.py
scripts/wp4_safe_fixture_planner.py
scripts/wp4_safe_fixture_recipe.py
scripts/wp4_safe_native_manifest.py
scripts/wp4_safe_native_storage.py
scripts/wp4_safe_native_transport.py
scripts/wp4_uat_server.py
tests/fixtures/kpi_policy_v1.json
tests/fixtures/wp1_manual_cases_v1.json
tests/test_ai_evaluation.py
tests/test_api_docs.py
tests/test_docker_archive.py
tests/test_f2_creation.py
tests/test_f3_page.py
tests/test_f4_page.py
tests/test_f5_page.py
tests/test_f6_page.py
tests/test_observability.py
tests/test_overview.py
tests/test_p12_demo.py
tests/test_p1_demo_boundary.py
tests/test_portal_presentation.py
tests/test_publication_security.py
tests/test_read_tool_answer.py
tests/test_wp2_api.py
tests/test_wp2_api_database.py
tests/test_wp2_canonical_workbook.py
tests/test_wp2_cases.py
tests/test_wp2_cases_database.py
tests/test_wp3_n8n_local.py
tests/test_wp3_preview.py
tests/test_wp3_preview_local.py
tests/test_wp3_workflow.js
tests/test_wp4_attempt_workflow.js
tests/test_wp4_custody_coverage_contract.py
tests/test_wp4_decision_database.py
tests/test_wp4_decisions.py
tests/test_wp4_dispatch_adapter.py
tests/test_wp4_dispatch_adapter_database.py
tests/test_wp4_dispatch_database.py
tests/test_wp4_dispatch_ipc.py
tests/test_wp4_dispatch_native_contract.py
tests/test_wp4_portal.py
tests/test_wp4_portal_attempt_api_database.py
tests/test_wp4_portal_attempts_database.py
tests/test_wp4_portal_auth_database.py
tests/test_wp4_portal_database.py
tests/test_wp4_portal_publication_database.py
tests/test_wp4_portal_publication_reads_database.py
tests/test_wp4_portal_registry.py
tests/test_wp4_portal_review_v3_database.py
tests/test_wp4_portal_transition_api_database.py
tests/test_wp4_portal_transition_database.py
tests/test_wp4_portal_uat.py
tests/test_wp4_portal_worker_database.py
tests/test_wp4_proposals.py
tests/test_wp4_proposals_database.py
tests/test_wp4_publication_contract.py
tests/test_wp4_publication_files.py
tests/test_wp4_publication_workflow.js
tests/test_wp4_recovery_design.py
tests/test_wp4_requests_v2.py
tests/test_wp4_reviewer.py
tests/test_wp4_reviewer_database.py
tests/test_wp4_reviewer_local.py
tests/test_wp4_safe_fixture_contract.py
tests/test_wp4_safe_fixture_planner.py
tests/test_wp4_worker_provisioning.py
tests/wp3_http_fixture.py
tests/wp4_attempt_n8n_fixtures.py
tests/wp4_attempt_worker_http.py
tests/wp4_dispatch_ipc_server.py
tests/wp4_dispatch_native_suite.py
tests/wp4_n8n_restore_receiver.py
tests/wp4_portal_worker_http.py
tests/wp4_publication_n8n_fixtures.py
tests/wp4_recovery_fixtures.py
tests/wp4_recovery_probe.py
tests/wp4_recovery_worker_http.py
tests/wp4_uat_fixtures.py
workflows/README.md
workflows/f2_create_report_staged.json
workflows/p12_create_report.json
workflows/p12_human_decision.json
workflows/p12_report_core.json
workflows/p1_manual_report.json
workflows/p2_read_agent_core.json
workflows/p2_read_agent_demo.json
workflows/p3_mcp_agent_core.json
workflows/p3_mcp_agent_demo.json
workflows/p4_rag_core.json
workflows/p4_rag_demo.json
workflows/p4_rag_index.json
workflows/read_tool_answer.js
workflows/wp3_manual_draft.json
```

</details>

<details>
<summary>PRIVATE — exact paths (13)</summary>

```text
AGENTS.md
PROJECT.md
START_HERE.md
STATUS.md
docs/CODEX_SETTINGS.md
docs/F2_DEPLOYMENT.md
docs/HANDOFF_VALIDATION.md
docs/PORTABLE_RECOVERY.md
docs/SECURITY_AND_OPERATIONS.md
docs/SETUP_AND_ACCOUNTS.md
docs/TOOL_READINESS_2026_10_08.md
prompts/FIRST_CODEX_TASK.md
prompts/NEXT_TASK.md
```

</details>

<details>
<summary>REVIEW — exact paths (162)</summary>

```text
ARCHITECTURE.md
SHA256SUMS
config/g0-versions.lock.json
config/versions.pending.json
demo/compose.yaml
demo/p2.compose.yaml
demo/p4.compose.yaml
docs/ADR_LOCAL_APPROVAL_V1.md
docs/ADR_PORTAL_PUBLICATION_V2.md
docs/G0_IMPORT_STRESS.md
docs/G0_INTEGRATION.md
docs/G0_MODEL_TRIAL.md
docs/G0_PREFLIGHT.md
docs/G0_RESOURCE_PROFILE.md
docs/G0_RESULTS.md
docs/WP2_ASOF_CUTOFF.md
docs/WP2_CALCULATION_API.md
docs/WP2_CANONICAL_WORKBOOK_RECONCILIATION.md
docs/WP2_CLASSIFICATION_RESULTS.md
docs/WP2_COMPARISON_REPORT.md
docs/WP2_COMPARISON_WORKBOOK_RECONCILIATION.md
docs/WP2_DETERMINISTIC_REPORT.md
docs/WP2_IMPORT_RESULTS.md
docs/WP2_INVOICE_CONSISTENCY.md
docs/WP2_OVERLAP_POLICY.md
docs/WP2_PERIOD_KPIS.md
docs/WP2_REPORT_PERSISTENCE.md
docs/WP2_SOURCE_SCHEMA.md
docs/WP3_MANUAL_DRAFT_WORKFLOW.md
docs/WP3_READ_ONLY_PREVIEW.md
docs/WP4_ADMISSION_CONTROLLER_CONTRACT.md
docs/WP4_AUTHENTICATED_CLOSED_CONTROLLER.md
docs/WP4_AUTHENTICATED_CLOSED_CONTROLLER_PLAN.json
docs/WP4_AUTHENTICATED_CLOSED_FOUNDATION.md
docs/WP4_AUTHENTICATED_CLOSED_RESULTS.md
docs/WP4_BUSINESS_GUARD_REHEARSAL.md
docs/WP4_CLOSED_CONTROL_PRIMITIVES.md
docs/WP4_CODEX_DOCKER_ACCESS_PROPOSAL.md
docs/WP4_CONTINUOUS_CUSTODY_CONTRACT.md
docs/WP4_CONTINUOUS_CUSTODY_FOUNDATION.md
docs/WP4_CONTINUOUS_CUSTODY_NATIVE_RESULTS.md
docs/WP4_CONTINUOUS_CUSTODY_PLAN.json
docs/WP4_CONTINUOUS_CUSTODY_PREPARATION_DIAGNOSTICS.md
docs/WP4_CONTINUOUS_CUSTODY_RUNNER.md
docs/WP4_CONTROLLER_CUSTODY_REHEARSAL.md
docs/WP4_COORDINATED_CHECKPOINT_PLAN.md
docs/WP4_COORDINATED_CHECKPOINT_RESULTS.md
docs/WP4_CRASH_RESTORE.md
docs/WP4_CUSTODY_GUARD_COVERAGE.md
docs/WP4_DECISION_OUTBOX_FOUNDATION.md
docs/WP4_DEPLOYMENT_PREFLIGHT.md
docs/WP4_DOCKER_ONESHOT_DIAGNOSTIC.md
docs/WP4_EXPIRED_APPROVAL_RECOVERY_DESIGN.md
docs/WP4_EXPLICIT_APPROVAL_REQUESTS.md
docs/WP4_IMMUTABLE_APPROVAL_PROPOSALS.md
docs/WP4_LOCAL_PUBLICATION_FILES.md
docs/WP4_N8N_DURABLE_ATTEMPTS.md
docs/WP4_N8N_PORTAL_PUBLICATION.md
docs/WP4_N8N_RESTORE.md
docs/WP4_NATIVE_DISPATCH_HARNESS.md
docs/WP4_OWNER_MANUAL_PILOT.md
docs/WP4_OWNER_PORTAL.md
docs/WP4_OWNER_READ_AUTH.md
docs/WP4_POPULATED_DEPLOYMENT_DESIGN.md
docs/WP4_POPULATED_PUBLICATION_REGRESSIONS.md
docs/WP4_POPULATED_REHEARSAL_001.md
docs/WP4_POPULATED_REHEARSAL_002.md
docs/WP4_POPULATED_REHEARSAL_003.md
docs/WP4_POPULATED_REVIEW_REGRESSIONS.md
docs/WP4_POPULATED_STORE_PREFLIGHT.md
docs/WP4_PORTAL_ATTEMPT_API.md
docs/WP4_PORTAL_AUTH_V2.md
docs/WP4_PORTAL_DECISIONS.md
docs/WP4_PORTAL_LEGACY_TRANSITION.md
docs/WP4_PORTAL_PUBLICATION_FOUNDATION.md
docs/WP4_PORTAL_PUBLICATION_READS.md
docs/WP4_PORTAL_REVIEW_V3.md
docs/WP4_PORTAL_TRANSITION_API.md
docs/WP4_PORTAL_WORKER_ATTEMPTS.md
docs/WP4_PUBLICATION_BOUNDARY_EVALUATION.md
docs/WP4_PUBLICATION_DISPATCH_ADAPTER.md
docs/WP4_PUBLICATION_DISPATCH_LEDGER.md
docs/WP4_SAFE_CHECKPOINT_COMPATIBILITY_BLOCKER.md
docs/WP4_SAFE_NATIVE_FIXTURE_DESIGN.md
docs/WP4_SAFE_NATIVE_FIXTURE_I1.md
docs/WP4_SAFE_NATIVE_FIXTURE_I2.md
docs/WP4_SAFE_NATIVE_FIXTURE_I3.md
docs/WP4_SAFE_NATIVE_FIXTURE_N1_OFFLINE_IMPLEMENTATION.md
docs/WP4_SAFE_NATIVE_FIXTURE_N1_READINESS.md
docs/WP4_SAFE_PUBLIC_CHECKPOINT.md
docs/WP4_SESSION_INVENTORY_REHEARSAL.md
docs/WP4_STORAGE_STARTUP_DIAGNOSTIC.md
docs/WP4_SYNTHETIC_PORTAL_UAT.md
g0/api/Dockerfile
g0/api/main.py
g0/api/requirements.txt
g0/compose.yaml
g0/workflow.json
scripts/README.md
scripts/build_wp4_attempt_workflow.py
scripts/check_wp4_deployment_preflight.py
scripts/check_wp4_n8n_attempts_local.py
scripts/check_wp4_n8n_restore_local.py
scripts/check_wp4_recovery_local.py
scripts/check_wp4_uat_local.py
scripts/check_wp4_uat_pilot_local.py
scripts/portable_backup.ps1
scripts/portable_backup.py
scripts/test_p3_consistency.py
scripts/wp4_acl_hardening_rehearsal.py
scripts/wp4_admission_failure_contract.py
scripts/wp4_authenticated_closed_foundation.py
scripts/wp4_authenticated_closed_rehearsal.py
scripts/wp4_business_guard_rehearsal.py
scripts/wp4_checkpoint_credentials.js
scripts/wp4_checkpoint_local.py
scripts/wp4_closed_control_rehearsal.py
scripts/wp4_continuous_custody_foundation.py
scripts/wp4_continuous_custody_runner.py
scripts/wp4_continuous_custody_scenarios.py
scripts/wp4_continuous_custody_transport.py
scripts/wp4_controller_custody_rehearsal.py
scripts/wp4_populated_publication_rehearsal.py
scripts/wp4_populated_rehearsal.py
scripts/wp4_populated_review_rehearsal.py
scripts/wp4_populated_store_rehearsal.py
scripts/wp4_portal_schema_rehearsal.py
scripts/wp4_safe_fixture_integration.py
scripts/wp4_safe_native_materializer.py
scripts/wp4_safe_public_checkpoint.py
scripts/wp4_session_inventory_rehearsal.py
tests/test_wp4_acl_hardening_rehearsal.py
tests/test_wp4_admission_failure_contract.py
tests/test_wp4_attempt_workflow_helpers.py
tests/test_wp4_authenticated_closed_foundation.py
tests/test_wp4_authenticated_closed_rehearsal.py
tests/test_wp4_business_guard_rehearsal.py
tests/test_wp4_checkpoint_local.py
tests/test_wp4_checkpoint_manifest.py
tests/test_wp4_closed_control_rehearsal.py
tests/test_wp4_continuous_custody_foundation.py
tests/test_wp4_continuous_custody_runner.py
tests/test_wp4_continuous_custody_transport.py
tests/test_wp4_controller_custody_rehearsal.py
tests/test_wp4_deployment_preflight.py
tests/test_wp4_n8n_restore_helpers.py
tests/test_wp4_populated_publication_rehearsal.py
tests/test_wp4_populated_rehearsal.py
tests/test_wp4_populated_review_rehearsal.py
tests/test_wp4_populated_store.py
tests/test_wp4_portal_schema_rehearsal.py
tests/test_wp4_recovery_helpers.py
tests/test_wp4_safe_fixture_integration.py
tests/test_wp4_safe_native_implementation.py
tests/test_wp4_safe_public_checkpoint.py
tests/test_wp4_session_inventory_rehearsal.py
tests/test_wp4_uat_local_helpers.py
tests/test_wp4_uat_pilot_helpers.py
tests/wp4_n8n_restore_cli.js
workflows/wp4_attempt_policy.js
workflows/wp4_manual_portal_attempts.json
workflows/wp4_manual_portal_publication.json
```

</details>

