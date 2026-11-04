# Business-effect measurement protocol

## Question

Does automation reduce active human effort for the same acceptable report, and does AI add benefit after deterministic automation is already present?

## Three paired variants

| Variant | Procedure | What it estimates |
| --- | --- | --- |
| A: Manual | Analyst follows documented steps using the agreed manual tools | Manual baseline |
| B: Deterministic automation | Import, validation, SQL, templates and normal human review; no AI | Automation benefit |
| C: Full AI-assisted process | Same pipeline plus model commentary/agent features appropriate to the release | Incremental AI contribution |

Keep cases, required deliverables, acceptance standards, and underlying data comparable. Do not deliberately handicap the manual method. Record tool experience and allowed aids.

## Pilot and larger evaluation

Run ten representative cases first to test the protocol, not to claim population-wide ROI. Include routine reports, cancellations, missing data, unusual volumes and failures where appropriate. Then set the larger evaluation size from variability and available time; disclose the chosen sample and coverage.

Counterbalance variant order across cases and avoid timing the same memorized solution immediately after seeing its automated answer. Keep practice cases outside the final evaluation. If one analyst performs all work, disclose that limitation.

## Record separately

- Active human minutes, including setup specific to the case, review, correction and recovery.
- End-to-end elapsed time, including model/queue waits.
- Setup/development effort, model downloads and environment preparation as one-time costs.
- Completion/acceptance result, numerical correctness, source coverage and unsupported statements.
- API/model calls, retries, model tokens when available, direct runtime charges and failures.
- Dataset hash, case definition, variant, sequence, date, software/prompt version and reviewer.

Use `evidence/templates/measurement.csv`. Never fill time or quality fields from an LLM guess. Failed attempts and manual fallback effort remain in the results.

The frozen WP1 pilot windows, owner-run manual instructions and blank report form are in `docs/WP1_MANUAL_BASELINE.md`, `tests/fixtures/wp1_manual_cases_v1.json` and `evidence/templates/manual_report.md`. Case selection is verified, but no A/B/C timing or quality observation is recorded yet.

## Analysis

Compute paired per-case differences: `A - B` for deterministic automation, `B - C` for incremental AI, and `A - C` for the full process. Positive values mean lower human effort; negative AI differences are valid findings. Report medians and distribution/uncertainty along with means where useful. Quality must remain acceptable before time reduction is interpreted as improvement.

Wilson intervals apply to binary success proportions. Macro-F1 or retrieval metric uncertainty requires an appropriate resampling approach, with clustering when multiple questions share the same report/document. No universal claim that one interval is always wider is made.

## Economic scenario

Measured hours saved per case times an assumed monthly volume gives a scenario, not observed employer savings. Show labor rate, volume, one-time development/setup, maintenance, failure/rework and actual runtime costs separately. Local hardware/electricity are not literally free merely because software has no subscription.

## Resume wording after evidence

Template only: "Designed and implemented an n8n reporting automation on real retail records; reduced median active preparation/review time from [A] to [C] minutes across [N] pilot cases, with [quality measure]. Deterministic automation accounted for [A-B], and AI contributed [B-C]."

Replace brackets only with measured values. Identify the work as a reproducible portfolio pilot until a real organisation adopts it.
