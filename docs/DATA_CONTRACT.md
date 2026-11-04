# Data contract

## Provenance

Preferred source is [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii). The publisher describes 1,067,371 historical rows from 2009-12-01 through 2011-12-09, distributed as a 43.5 MB XLSX, under CC BY 4.0. The complete downloaded workbook was verified in the current environment on 2026-09-29: the row count and date coverage match, and missing values are present. See `G0_DATA_PROFILE.md`. Attribute the dataset and preserve its license.

The two annual worksheets overlap from 2010-12-01 through 2010-12-09. The full-file profile found 22,202 matching value groups and 22,523 matched row occurrences on each side. Preserve both physical source identities. A tested, source-specific **analytical selection** policy now chooses the newer sheet from 2010-12-01 after verifying exact overlap multiset equality; see `WP2_OVERLAP_POLICY.md`. It does not delete or deduplicate physical rows. A bounded merged SQL KPI/report payload exists, but no end-to-end delivered report is claimed.

Fallback: [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online-retail). Do not infer no missing values from its metadata. Both describe a UK giftware retailer and GBP prices; there is no confirmed wholesale-customer flag. December 2011 is partial.

## Raw schema and mapping

Preserve actual worksheet headers and map them explicitly into `invoice_no`, `stock_code`, `description`, `quantity`, `invoice_datetime_raw`, `unit_price_gbp`, `customer_id`, `country`. Online Retail II may use different original column names; inspect the file rather than hardcoding the sibling dataset's headers.

The verified Online Retail II workbook uses this mapping on both worksheets:

| Source header | Canonical field |
| --- | --- |
| `Invoice` | `invoice_no` |
| `StockCode` | `stock_code` |
| `Description` | `description` |
| `Quantity` | `quantity` |
| `InvoiceDate` | `invoice_datetime_raw` |
| `Price` | `unit_price_gbp` |
| `Customer ID` | `customer_id` |
| `Country` | `country` |

Each row receives `source_file_sha256`, `worksheet`, `source_row_number`, `ingested_at`, schema version and raw values. Source row identity is the file hash + worksheet + physical row number. Equal business values do not prove an accidental duplicate.

Store codes/identifiers as strings. A missing customer remains missing. Preserve product descriptions; do not invent customer names, demographic fields, stock levels, procurement cost or retailer procedures.

## Inclusion policy, version 1

| Row class | Rule | Treatment |
| --- | --- | --- |
| Sale | Non-cancellation invoice, quantity > 0, finite price >= 0, valid required keys/time | Included in sale aggregates |
| Cancellation | Invoice begins with C, quantity < 0, finite price >= 0, valid keys/time | Included as negative cancellation value |
| Other adjustment | Negative quantity without C, or contradictory cancellation/quantity signs | Separate adjustment bucket; excluded from the initial net-sales formula and disclosed |
| Invalid | Invalid/missing invoice or time, non-numeric quantity/price, negative price, or missing essential product key | Quarantined or specifically excluded with an explicit reason |
| Customer missing | Otherwise valid row with null customer_id | Retained for sales; excluded only from customer-level metrics |
| Description missing | Valid product key with missing text | Retained for sales; unavailable for description-based retrieval |
| Zero price / zero quantity | Zero price sale is flagged; zero quantity is a separate non-sales row | Account separately; no division-by-zero side effects |

Report counts and monetary impact where calculable for every exclusion. A C invoice indicates cancellation in the source dictionary; it is not proof of a physical product return, completed refund, or why a customer cancelled.

## Monetary and temporal rules

Use Decimal in Python and NUMERIC in PostgreSQL. Preserve source precision; round only for a documented display/export purpose. Name rounding policy and scale. Check XLSX numeric conversion against representative cells; avoid silently forcing all prices to two decimals before aggregation.

Keep naive source time exactly as provided. Europe/London is a documented interpretation assumption, not a supplied timezone. Handle DST ambiguity explicitly before any UTC conversion. Execution/audit times use actual UTC; source_time and ingested_at never share a misleading field.

A report period is start-inclusive/end-exclusive. Define whether cancellation value is attributed to its recorded date; v1 uses the recorded cancellation date, without attempting unproven matching to an earlier original sale. Year-over-year compares aligned complete periods, never a partial December against an entire December.

## Replay and lineage

The bounded WP2 calculation API now requires offset-bearing transport timestamps and explicit `Europe/London-assumed` acknowledgment before mapping them to naive source-clock boundaries. It rejects ambiguous/nonexistent boundaries and current/prior periods crossing DST. Migration 012 also conservatively bounds both periods and cutoff by the canonical observed-row span, not a guarantee of uninterrupted calendar coverage; see `WP2_CALCULATION_API.md`. Raw source times are unchanged. This is not the complete case/revision or document/outcome as-of path.

Keep an archive snapshot fixed during an evaluation. Migration 009 adds a source-time-exclusive as-of cutoff to canonical KPI SQL: require `period_end_exclusive <= source_as_of_exclusive`, filter selected invoice-identity checks to earlier source timestamps, and bind the immutable source hash. This is only the invoice-time SQL portion of the rule; whole-file integrity guards still inspect the complete pinned archive. Do not let later document versions or outcome labels inform an earlier case; those stores and the full report/AI evidence path are not implemented. See `WP2_ASOF_CUTOFF.md`. The application's replay endpoint is our own adapter over real historical data, not a live merchant API.

## Full-file reconciliation

Account for all worksheets and rows, including invalid ones. Record actual min/max dates, null counts, type problems, duplicates by value versus row identity, distinct product IDs, exclusions and totals. If counts differ from the publisher, investigate and disclose; do not delete rows to force a match.
