# KPI dictionary, policy v1

These definitions govern deterministic SQL. AI may explain validated results but cannot redefine denominators. All monetary values are GBP. Dates use the data contract and period `[start, end)`.

| KPI | Definition | Limitations |
| --- | --- | --- |
| Recorded sales value | Sum(quantity * unit_price) over accepted sale rows | Revenue proxy; not audited revenue or profit |
| Recorded cancellation value | Negative sum(quantity * unit_price) over accepted cancellation rows, reported as a positive magnitude | Recorded-date cancellation amount, not a physical-return rate |
| Net recorded sales | Recorded sales value minus recorded cancellation value | Other adjustments excluded and disclosed; not cash flow |
| Sales invoice count | Distinct accepted non-C invoice numbers in period, after invoice-consistency checks | Source invoice identifiers, not a new order model |
| Average sales invoice value | Recorded sales value / sales invoice count | Null if denominator is zero; report segment effects |
| Active identified customers | Distinct non-null customer IDs on accepted sale rows | Anonymous/unidentified sales are separately counted |
| Customer coverage | Accepted sale rows with a customer ID / all accepted sale rows | Row-based completeness, not a people estimate |
| Units sold | Sum of quantity on accepted sale rows | Net units, if added, needs a separately named definition |
| Period change | (current comparable KPI - prior KPI) / absolute(prior KPI) | Null/flag when baseline is zero; disclose date coverage |
| Cancellation-to-sales value ratio | Recorded cancellation magnitude / recorded sales value | Different source periods may contribute; not a matched-order return probability |

## Unapproved HTML display policy

The later unapproved HTML preview uses `decimal-half-up-v1`: Decimal ROUND_HALF_UP to two places for GBP and percentages (stored fraction times 100), integral counts, signed changes and explicit zero-denominator/baseline nulls. Each stored numeric value and escaped original JSON remain available without changing SQL bytes/hash. This supersedes pending-display statements below only for this private HTML projection, not PDF or approved publication artifacts. See `WP3_READ_ONLY_PREVIEW.md` for evidence and visual/reviewer limits.

## Later segmentation

RFM uses an explicit as-of date, accepted sales only, non-null customer IDs, and a declared observation window. High-volume segments are operational proxies; they are not confirmed wholesalers. Report summaries by the declared segments rather than implying that all customers have the same purchasing pattern.

## Alerts

Start with explicit configurable business rules and data-quality flags. A change is an observed deviation, not an established causal explanation. Seasonal baselines and statistical detectors enter only with time-based validation and comparisons to simpler rules.

## SQL verification

Use small hand-checked fixtures that include a cancellation, a missing customer, a zero denominator and a period boundary. DuckDB may later provide an additional computation path; do not call copied SQL independent validation without a separately reviewed formula and golden cases.

A read-only Decimal/Fraction calculation from the pinned original XLSX independently matched all 20 canonical SQL fields for one cross-cutover real period and all ten frozen WP1 cases; see `docs/WP2_CANONICAL_WORKBOOK_RECONCILIATION.md`. DuckDB remains a possible additional computation path, not a prerequisite for the current bounded result.

The bounded single-sheet SQL implementation is `retail.period_kpis_v1` in migrations 004–005; see `docs/WP2_PERIOD_KPIS.md` and `docs/WP2_INVOICE_CONSISTENCY.md`. Migration 008 adds `retail.canonical_period_kpis_v1` over the guarded cross-sheet selection; see `docs/WP2_CANONICAL_KPIS.md`. It also rejects a sale invoice number used on both selected worksheets, as well as contradictory known Customer IDs/countries. Missing values do not conflict and differing line timestamps are allowed. Migration 009 adds `retail.canonical_period_kpis_asof_v1` to restrict invoice-time evidence by a bound source-time cutoff; see `docs/WP2_ASOF_CUTOFF.md`. This does not establish document/outcome as-of control or identity across separate source snapshots. Ratios stay NUMERIC and unrounded in SQL; the output/display rounding policy is pending.

Migration 010 packages those 20 as-of KPI fields and checked, overlapping policy-v1 quality-code counts into a versioned deterministic JSONB payload; see `docs/WP2_DETERMINISTIC_REPORT.md`. This is not a persisted, formatted or approved report artifact.

Migration 011 adds a fixed seven-calendar-day comparison for six headline metrics, with signed absolute deltas and fractional relative change using `abs(prior)`; zero baselines produce null plus `zero_baseline`. Both periods share the case cutoff and snapshot. See `docs/WP2_COMPARISON_REPORT.md` for metric scope, coverage limitations and bounded evidence. Ratios and quality counts remain in the nested period payloads without change metrics.

All ten frozen WP1 current/prior pairs now independently match their source-XLSX arithmetic through migration 011, including all 20 KPI fields per period and six change objects per case. See `docs/WP2_COMPARISON_WORKBOOK_RECONCILIATION.md`. This includes a real negative net-sales baseline and null/flagged zero baselines, but not an independent quality-code audit or end-to-end acceptance.
