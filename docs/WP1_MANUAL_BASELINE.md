# WP1 owner-run manual baseline protocol

Status: case selection verified on the local workbook; **no owner run, elapsed time, active time, quality result, or savings has been observed**. This is a pilot protocol, not a historical retailer procedure. It operationalizes variant A in `docs/MEASUREMENT.md`; variants B and C must later use the same frozen cases and deliverables.

## Fixed source and cases

Use the unmodified UCI Online Retail II workbook at `data/raw/uci_502/online_retail_II.xlsx`, SHA-256 `BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980`, and only worksheet `Year 2010-2011`. The ten one-hour, start-inclusive/end-exclusive windows are frozen in `tests/fixtures/wp1_manual_cases_v1.json`. Source timestamps are naive workbook times. The comparison window is the same hour exactly seven calendar days earlier, on the same worksheet. These selections avoid the two-worksheet overlap; do not concatenate or deduplicate equal-valued rows.

| Case | Current window start | Selection focus |
| --- | --- | --- |
| M01 | 2011-05-08 15:00 | Routine sales |
| M02 | 2011-01-28 09:00 | Sales and cancellations |
| M03 | 2011-10-06 20:00 | Cancellations but no sales |
| M04 | 2011-06-10 17:00 | Sales with missing Customer ID |
| M05 | 2011-02-28 14:00 | Zero-price sales |
| M06 | 2011-06-10 10:00 | Other adjustments |
| M07 | 2011-08-12 14:00 | Invalid negative prices |
| M08 | 2011-07-14 10:00 | Mixed exceptions |
| M09 | 2011-11-11 09:00 | Higher row volume |
| M10 | 2011-01-01 00:00 | Empty current and comparison windows |

The case-check script is for the evaluator, not a source of KPI answers for the analyst. From the repository root, run the bundled Python runtime shown in `docs/G0_DATA_PROFILE.md` with `scripts/check_wp1_manual_cases.py`. It checks the workbook hash, dates, source features and counts; it does **not** calculate report KPIs or verify the analyst's answers. If the hash or case check fails, stop and investigate rather than silently replacing the source. M09 is intentionally more demanding; retain failures and actual effort instead of omitting it from results.

## Freeze the run conditions before timing

1. Record the analyst, reviewer code, spreadsheet/tool version, permitted features and prior experience. Normal interactive spreadsheet filters, formulas and pivots are allowed; do not deliberately handicap the manual variant. If scripts or other aids are part of the owner's genuine manual method, record them and use the same definition for all A runs. Do not call the planned product workflow or use its precomputed KPI output as a manual aid.
2. Save a blank copy of `evidence/templates/manual_report.md` per case under ignored `evidence/private/wp1/`. Keep working extracts, source-row references and any customer or invoice identifiers there too. Never edit the source workbook or commit private working files.
3. Reserve an unscored practice case outside M01–M10 to learn the form and tools. Schedule timed A/B/C runs with order counterbalanced where feasible, separated enough to reduce answer memorization. If A is collected before B/C exists, explicitly disclose the A-first order as a pilot limitation.
4. Define the start as opening the case instructions and the stop as review disposition plus a locally saved report/follow-up. Record wall-clock start/finish and active analyst/reviewer work separately; put their sum in `active_human_minutes` and the breakdown in notes. Pause active timing for unrelated interruptions but keep elapsed time running. Include setup specific to the case, checking, correction and recovery. Do not estimate times after the fact.

## Manual procedure for each case

1. Verify the workbook hash once per session. In a working copy, retain each physical worksheet row number. Filter current and comparison windows by `start <= InvoiceDate < end`; keep every source row, including identical-valued rows. Note row counts and whether a window is empty.
2. Classify each row using `docs/DATA_CONTRACT.md`: sale, cancellation, other adjustment, zero-quantity non-sale, or invalid, with reasons. Missing Customer ID and missing Description do not by themselves remove an otherwise valid sale. Zero-price sales remain included; negative prices are invalid. A `C` invoice indicates a recorded cancellation, not a proven refund/return.
3. Use `docs/KPI_DICTIONARY.md`. For current and prior windows, record sale rows, cancellation rows, other adjustments, invalid rows, missing-customer sale rows and zero-price sale rows. Calculate recorded sales GBP, cancellation magnitude GBP, net recorded sales GBP, units sold, distinct sales invoices, average sales invoice value, distinct identified customers, customer coverage and cancellation-to-sales value ratio. Show null/not applicable for zero denominators, never divide by zero. Compare net recorded sales to the prior window only if the prior value is nonzero; otherwise state that the percentage comparison is undefined. Retain source precision and declare display rounding; ordinary spreadsheets may use binary floating point, so later verify monetary results independently with Decimal/NUMERIC and record discrepancies.
4. Write up to three factual observations and one locally saved follow-up item, grounded in the calculated numbers or source-row identities. Do not infer profit, confirmed wholesale status, physical returns, or the retailer's actual internal practice. Complete the private report template and preserve the working spreadsheet/formulas.
5. Have the reviewer inspect the exact saved revision, arithmetic and exception treatment. Record accept/reject/needs-correction and any correction time. If the owner reviews their own work, label it self-review. Do not publish externally. A provisional review is not independent numerical acceptance; leave `accepted` and `numerical_errors` blank in `evidence/templates/measurement.csv` until an independent reference check is available.
6. Add one row to a **private copy** of `evidence/templates/measurement.csv`: `case_id`, `variant=A`, actual sequence and timestamp, source hash, period, active and elapsed minutes, tool/reviewer codes and notes. Record failures, interruptions, assistance and manual fallback. Use `runtime_charge=0` only if actually zero, and keep one-time setup separate. Never populate unknown quality or time fields with guesses.

## Comparable evaluation and exit condition

Variant B (deterministic) and C (AI-assisted) must later receive the same source, windows, required fields, commentary limit and review standard. The SQL/reference check must compare required values at source precision with a declared display-rounding rule and investigate discrepancies; copied formulas are not independent validation. AC-25 remains **NOT RUN** until ten paired A/B/C cases, quality assessment and actual timing records exist. Revise the AS-IS BPMN if the observed manual steps differ from its illustrative design. Do not report a savings number from this protocol alone.
