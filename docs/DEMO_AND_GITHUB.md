# GitHub publication and demonstration

## Canonical repository

The owner supplies GitHub account, repository name and visibility. A suggested slug is `retail-analytics-automation`; it is not an existing URL. Code, workflow exports, migrations, deployment, tests and English documentation live together. Avoid shipping model weights, full archives, personal identifiers, secrets or raw sensitive logs in Git.

Once identity is known, initialise/reuse local Git, configure the owner's actual commit identity, perform a secret/artifact review, and create/push the chosen remote. GitHub access is not evidence that the product's GitHub integration has been tested.

## Lightweight importable workflow

Target: a compatible existing n8n instance. The reviewer selects `Import from URL` and pastes the raw GitHub JSON URL. This imports one workflow definition; it does not install services, grant cloud access or transfer account credentials. Confirm this route on the pinned supported version before publishing a working button/link.

Design the basic demo with a Manual Trigger, a small attributed slice of real archived data, JS transformations, branching, validation and a deterministic report. Include source row references/hash and explicitly name the restricted sample. Supply the slice from a verified actual download; do not fabricate retail rows to satisfy this contract.

The zero-credential demo may show pre-recorded AI output only if visibly labelled as recorded. It cannot count as working inference. A real optional AI branch requires the reviewer's own reachable model/provider setup. Do not assume n8n Cloud can reach the owner's `localhost` services.

Acceptance: import into a fresh supported instance; execute the basic path; show correct sample metrics and a failure branch; use English labels/sticky notes; require no community/paid node or credential for the basic path. Test expected links to sub-workflows if the demo later expands, rather than assuming imported IDs automatically match.

An existing n8n Cloud account may have its own charges. The free complete deployment uses self-hosted Community; no perpetual free Cloud plan is promised.

## Full local product

The final bootstrap should verify prerequisites, generate local secrets, fetch verified data and model artifacts, apply migrations, import/sanitise workflows, guide owner-account creation and verify health. A first download takes time and storage. Document tested commands after implementation. The full stack must work independently of the author's running computer.

## Employer-facing evidence

README starts with problem, result, role and caveats. Then show process, architecture, key workflow screenshots, acceptance evidence, measurement report, quick start and limits. A 2–3 minute English video should show a normal report, source evidence, approval, an intentional failure, recovery and measured results if available.

Before publication check English-only project text, source/license attribution, sanitized credential references, reproducibility, evidence links, actual status, and no unsupported claims of live merchant deployment or ROI.
