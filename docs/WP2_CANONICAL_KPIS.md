# WP2 canonical cross-sheet period KPI SQL

Date: 2026-09-29. Status: **verified in the current PostgreSQL 17.11 validation database for the bounded merged SQL calculation and synthetic golden cases**. This is not a complete report, API/n8n workflow, independent real-period monetary validation, or AC-05/AC-06 release pass.

Migration `db/migrations/008_canonical_period_kpis_v1.sql` adds `retail.canonical_period_kpis_v1(snapshot_hash, start_inclusive, end_exclusive)`. It first runs the complete-import, sheet-domain and exact-overlap checks from migrations 006–007. It then aggregates only policy-v1 lines selected by the fixed UCI 502 worksheet cutover (older sheet before 2010-12-01, newer sheet from then onward) within a half-open source-time period. Money uses PostgreSQL `NUMERIC`; distinct invoice/customer counts and ratios are recomputed from selected lines, never summed from two sheet-level reports. Invalid and other-adjustment monetary effects are disclosed separately from net recorded sales. An empty period returns zero sums/counts and null zero-denominator ratios.

For each accepted sale invoice present in the requested period, the function checks all its selected lines across the canonical snapshot. Contradictory known Customer IDs/countries or the same invoice number appearing on both canonical worksheets block the result with an affected-invoice count, not raw identifiers. This is stricter than the single-sheet gate and avoids treating a cross-sheet number collision as a proven single order. The real archive has 41,938 canonical accepted sale invoice groups, zero cross-sheet number collisions and zero conflicting known Customer IDs/countries in an aggregate-only check.

## Exact checks

Apply migration 008 once after migration 007, then run the rollback-only SQL test from the repository root:

```powershell
Get-Content -LiteralPath db/migrations/008_canonical_period_kpis_v1.sql -Raw -Encoding UTF8 | docker exec -i raa-g0-postgres-1 psql -X -v ON_ERROR_STOP=1 -1 -U g0_user -d raa_wp2_validation -f -
Get-Content -LiteralPath db/tests/008_canonical_period_kpis_v1.sql -Raw -Encoding UTF8 | docker exec -i raa-g0-postgres-1 psql -X -v ON_ERROR_STOP=1 -U g0_user -d raa_wp2_validation -f -
```

The synthetic test loaded 14 physical lines across two annual sheets; six overlap lines on each side had identical typed raw-value multisets. The canonical selection contained eight lines: one older pre-cutover line, six newer overlap lines (including two equal-valued sale lines) and one newer post-overlap line. Hand-checked expected results for `[2010-11-30, 2010-12-11)` were:

| Measure | Expected and observed |
| --- | ---: |
| Selected / sale / cancellation / other / invalid / zero-quantity rows | 8 / 4 / 1 / 1 / 1 / 1 |
| Sales / cancellation magnitude / net recorded sales, GBP | 14 / 2 / 12 |
| Other adjustment / invalid signed value, GBP | -3 / -4 |
| Distinct sale invoices / average sales invoice value | 3 / 14÷3 |
| Identified customers / missing-customer sale rows / customer coverage | 1 / 1 / 3÷4 |
| Units sold / cancellation-to-sales value ratio | 6 / 1÷7 |

The same test checked overlap-day value GBP 8 (not GBP 16 from both physical copies and not GBP 4 from collapsing equal-valued rows within the selected sheet), a cancellation-only period, an empty period, and rejection of a pre-cutover sale reusing a post-cutover invoice number even when the requested interval contains only the latter. It returned `PASS|merged-kpi-golden|cross-cutover-invoice-guard` and `ROLLBACK`. The earlier single-sheet 26-value golden test and overlap-policy test both passed again after migration 008.

Read-only real archive smoke for `[2010-11-30, 2010-12-02)` returned 5,524 selected rows, 5,374 sale rows, 147 cancellation rows, GBP 118,989.87 sales, GBP 4,829.03 cancellation magnitude, 260 distinct sale invoices and unrounded average GBP 457.6533461538461538. Separate selected-date SQL aggregates were:

| Source selection | Rows | Sale rows | Cancellation rows | Sales GBP | Cancellation GBP | Sale invoices |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Older sheet, 2010-11-30 | 2,416 | 2,293 | 121 | 60,029.08 | 4,503.80 | 124 |
| Newer sheet, 2010-12-01 | 3,108 | 3,081 | 26 | 58,960.79 | 325.23 | 136 |

Those read-only source aggregates reconcile to the merged output, but they use the same normalized PostgreSQL data and were **not** independent workbook monetary validation. Later read-only XLSX/Decimal comparisons for this period and all ten frozen WP1 windows matched all 20 SQL fields per period; see `docs/WP2_CANONICAL_WORKBOOK_RECONCILIATION.md`. Post-test verification returned migration versions 1–8, zero synthetic raw/normalized rows, and 1,067,371 real raw plus 1,067,371 real normalized rows. No source row or database volume was removed. Focused work time was not recorded.

## Open limits

The function is bound to this UCI 502 sheet layout and cutover. Its guards read the full source snapshot on each call; release-path latency and a safe caching strategy are unmeasured. Migration 009 adds a separate source-time as-of KPI variant, but this v1 function still has a whole-snapshot invoice gate; see `docs/WP2_ASOF_CUTOFF.md`. Document revisions, outcome labels and complete case-time evidence protection are not implemented. Undated invalid rows require whole-snapshot quality accounting outside a period. Independent XLSX/Decimal evidence now covers the cross-cutover period and all ten frozen WP1 cases, but display rounding, comparative-period report, API/n8n orchestration and AC-05/AC-06 acceptance remain open.
