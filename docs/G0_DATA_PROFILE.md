# G0 Online Retail II full-file profile

Status: verified in the current environment on 2026-09-29. This is a full read-only profile of the downloaded UCI workbook, not a preview or metadata-only check.

## Source and integrity

Source: Daqing Chen, Online Retail II, UCI Machine Learning Repository, dataset 502, DOI [10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D), licensed under CC BY 4.0. The archive was downloaded from the [official UCI file endpoint](https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip).

| File | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `data/raw/online_retail_ii_uci_502.zip` | 45,622,418 | `572E36277C2390FBFDE10664750731E0A86F55E33470D91919085F0408E67BFB` |
| `data/raw/uci_502/online_retail_II.xlsx` | 45,622,278 | `BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980` |

The ZIP contains exactly one entry, `online_retail_II.xlsx`. Both files remain in the ignored raw-data directory. The profiler opened the XLSX in read-only/data-only mode and did not modify or remove source rows.

## Workbook reconciliation

| Worksheet | Data rows | Minimum invoice time | Maximum invoice time |
| --- | ---: | --- | --- |
| `Year 2009-2010` | 525,461 | 2009-12-01 07:45:00 | 2010-12-09 20:01:00 |
| `Year 2010-2011` | 541,910 | 2010-12-01 08:26:00 | 2011-12-09 12:50:00 |
| **Total** | **1,067,371** | **2009-12-01 07:45:00** | **2011-12-09 12:50:00** |

The total exactly matches the publisher's 1,067,371-row claim. There are no completely blank data rows. Actual headers on both worksheets are `Invoice`, `StockCode`, `Description`, `Quantity`, `InvoiceDate`, `Price`, `Customer ID`, and `Country`.

## Missing values and types

| Column | Null cells | Observed types |
| --- | ---: | --- |
| Invoice | 0 | 1,047,871 integer; 19,500 string |
| StockCode | 0 | 932,385 integer; 134,986 string |
| Description | 4,382 | 1,062,985 string; 4 integer; 4,382 null |
| Quantity | 0 | 1,067,371 integer |
| InvoiceDate | 0 | 1,067,371 datetime |
| Price | 0 | 1,057,347 float; 10,024 integer |
| Customer ID | 243,007 | 824,364 integer; 243,007 null |
| Country | 0 | 1,067,371 string |

No whitespace-only strings were found. Identifiers must be converted explicitly to strings during ingestion. Numeric description values are retained as source anomalies, not discarded. Missing Customer ID and Description values follow the retention rules in `DATA_CONTRACT.md`.

## Row classification

Money uses `Decimal` and is shown as signed source `Quantity × Price` in GBP without display rounding.

| Class | Rows | Signed value (GBP) | Treatment |
| --- | ---: | ---: | --- |
| Sale | 1,044,415 | 20,972,594.568 | Included in sale aggregates |
| Cancellation | 19,493 | -1,527,041.43 | Included as negative cancellation value |
| Other adjustment | 3,458 | 373.57 | Excluded from the initial net-sales formula and disclosed |
| Zero-quantity non-sale | 0 | 0 | Separate non-sales class |
| Invalid | 5 | -158,676.14 | Quarantined; all five have a negative unit price |

Other adjustments comprise 3,457 negative-quantity rows without a cancellation invoice prefix and one cancellation-prefixed invoice with non-negative quantity. The five invalid rows have calculable signed values but are excluded because negative prices violate the v1 contract.

Retention observations:

- 243,007 rows have no Customer ID; 243,002 are otherwise valid. The 238,795 sale rows without Customer ID represent GBP 3,229,165.39 and remain in sales aggregates.
- 4,382 rows have no Description; all are otherwise valid and remain eligible for sales calculations where applicable.
- 2,745 sale rows have zero price and remain flagged; their signed value is GBP 0.

Distinct non-null counts are 53,628 invoices, 5,305 stock codes, 5,942 customers, and 43 countries.

## Duplicate values and worksheet overlap

Every source row retains a unique physical identity: workbook hash, worksheet, and source row number. No row was removed.

| Scope | Duplicate value groups | Rows beyond the first occurrence |
| --- | ---: | ---: |
| `Year 2009-2010` | 6,418 | 6,865 |
| `Year 2010-2011` | 4,879 | 5,268 |
| Whole workbook | 32,907 | 34,335 |

The worksheet date ranges overlap from 2010-12-01 through 2010-12-09. A typed fingerprint over the eight mapped source values found 22,202 matching groups between the two worksheets and 22,523 matched row occurrences on each side. These may represent the same transactions repeated across the annual sheets, but equality alone does not authorize deletion. The future importer must preserve both source identities and apply a documented, provenance-aware analytical reconciliation policy before combining periods.

## Reproduction and evidence

Profiler: Python 3.12.14, openpyxl 3.1.5, `read_only=True`, `data_only=True`. The final full pass took 52.886 seconds in the current environment.

```powershell
& '${USER_HOME}\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\profile_online_retail_ii.py `
  --workbook data\raw\uci_502\online_retail_II.xlsx `
  --archive data\raw\online_retail_ii_uci_502.zip `
  --output evidence\private\g0\online_retail_ii_profile.json
```

The aggregate raw profile is stored at private historical evidence (not published), which is ignored by Git. This published report contains no raw rows, Customer IDs, invoice IDs, or product descriptions.

## Remaining risk

G0-02 verifies the complete source file and makes the preferred archive viable for subsequent checks. It does not prove PostgreSQL import capacity, application ingestion, local-model quality, or the final overlap reconciliation policy; those remain in G0-03 through G0-05 and v0.1 implementation.
