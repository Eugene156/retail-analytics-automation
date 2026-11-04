"""Read-only HTML projection of exact stored SQL bytes; no browser-side arithmetic."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
from html import escape
import json
import re
from uuid import UUID

SOURCE_HASH = "BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980"
SCHEMA = "deterministic-comparison-report-v1"
DISPLAY_POLICY = "decimal-half-up-v1"
KPIS = {
    "period_source_rows": ("Selected source rows", "count"),
    "sale_rows": ("Accepted sale rows", "count"),
    "cancellation_rows": ("Accepted cancellation rows", "count"),
    "other_adjustment_rows": ("Other adjustment rows (excluded)", "count"),
    "zero_quantity_rows": ("Zero-quantity rows (excluded)", "count"),
    "invalid_rows": ("Invalid rows (excluded)", "count"),
    "sales_value_gbp": ("Recorded sales value", "money"),
    "cancellation_magnitude_gbp": ("Recorded cancellation magnitude", "money"),
    "net_recorded_sales_gbp": ("Net recorded sales", "money"),
    "other_adjustment_signed_gbp": ("Other adjustment signed value (excluded)", "money"),
    "invalid_signed_gbp": ("Calculable invalid signed value (excluded)", "money"),
    "invalid_value_calculable_rows": ("Invalid rows with calculable value", "count"),
    "sales_invoice_count": ("Sales invoice count", "count"),
    "average_sales_invoice_value_exact": ("Average sales invoice value", "money"),
    "active_identified_customers": ("Active identified customers", "count"),
    "missing_customer_sale_rows": ("Sales without Customer ID (retained)", "count"),
    "customer_coverage_exact": ("Customer coverage (sale-row basis)", "percent"),
    "units_sold": ("Units sold", "count"),
    "zero_price_sale_rows": ("Zero-price sale rows (retained)", "count"),
    "cancellation_to_sales_value_ratio_exact": ("Cancellation-to-sales value ratio", "percent"),
}
METRICS = ("sales_value_gbp", "cancellation_magnitude_gbp", "net_recorded_sales_gbp",
           "sales_invoice_count", "active_identified_customers", "units_sold")
NULLABLE = {"average_sales_invoice_value_exact", "customer_coverage_exact",
            "cancellation_to_sales_value_ratio_exact"}
CODES = ("missing_invoice", "missing_stock_code", "invalid_invoice_datetime", "invalid_quantity",
         "invalid_unit_price", "negative_unit_price", "zero_quantity", "negative_quantity_without_c",
         "c_invoice_non_negative_quantity", "missing_customer_id", "missing_description", "zero_price_sale")
BOUNDARIES = ("period_start_inclusive", "period_end_exclusive", "source_as_of_exclusive")
CSP = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
CSS = """
:root{color-scheme:light;font-family:system-ui,sans-serif;color:#172d39;background:#eef3f5}
*{box-sizing:border-box}body{margin:0}main{max-width:1120px;margin:32px auto;padding:0 24px 32px}
header{border-top:5px solid #17766b;padding:24px;background:#fff;border-radius:8px}
h1{margin:10px 0;font-size:32px;line-height:1.2}h2{font-size:22px;margin-top:0}
p,li{line-height:1.55}.eyebrow{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#46616d}
.status{display:inline-block;background:#fff0cc;color:#66470c;padding:7px 12px;border-radius:5px;font-weight:700}
section{background:#fff;padding:24px;margin-top:20px;border:1px solid #d8e3e7;border-radius:8px}
.muted{color:#526875;font-size:14px}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse}
th,td{padding:12px 10px;border-bottom:1px solid #d8e3e7;text-align:right;vertical-align:top;font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}thead{background:#f1f6f7}caption{text-align:left;padding-bottom:12px}
.value{white-space:nowrap}.exact{display:block;font-size:12px;color:#526875;overflow-wrap:anywhere;margin-top:4px}
dl{display:grid;grid-template-columns:180px 1fr;gap:10px}dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}
code,pre{font-family:ui-monospace,monospace;font-size:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;background:#f1f6f7}
summary{cursor:pointer;font-weight:600}footer{padding-top:20px;font-size:13px;color:#526875}
@media(max-width:640px){main{margin:16px auto;padding:0 12px 24px}header,section{padding:16px}h1{font-size:26px}dl{grid-template-columns:1fr;gap:6px}dd{margin-bottom:8px}th,td{padding:10px 8px}}
"""


def require(condition):
    if not condition:
        raise ValueError("Stored draft preview validation failed")


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def numeric(text):
    require(len(text) <= 64)
    value = Decimal(text)
    require(value.is_finite() and value.copy_abs() <= Decimal("1e24") and value.as_tuple().exponent >= -40)
    return value


def load(text):
    require(isinstance(text, str) and len(text.encode("utf-8")) <= 131072)
    return json.loads(text, parse_float=numeric, parse_int=numeric,
                      parse_constant=lambda _: require(False), object_pairs_hook=pairs)


def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected))


def number(value, count=False, nullable=False):
    if nullable and value is None:
        return
    require(isinstance(value, Decimal) and value.is_finite())
    if count:
        require(value >= 0 and value == value.to_integral_value())


def source_time(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}", value))
    return datetime.fromisoformat(value)


def validate(metadata_text, payload_text, case_id, revision):
    meta, report = load(metadata_text), load(payload_text)
    reviewed = meta.get("state") in ("approved", "rejected")
    keys(meta, ("case_id", "state", "revision", "request", "created_at", "updated_at",
                "payload_sha256", "schema_version", "approved", "published", "audit_events",
                *(("review_receipt",) if reviewed else ())))
    number(meta["revision"], count=True)
    require(meta["case_id"] == str(case_id) and revision == 1 and meta["revision"] == Decimal(1))
    require(meta["state"] in ("awaiting_approval", "approved", "rejected")
            and meta["approved"] is (meta["state"] == "approved") and meta["published"] is False)
    if reviewed:
        receipt = meta["review_receipt"]
        canonical, decision = receipt["canonical_payload_text"], receipt["decision"]
        require(hashlib.sha256(canonical.encode("utf-8")).hexdigest() == receipt["decision_sha256"]
                and load(canonical) == decision and decision["case_id"] == str(case_id)
                and decision["report_revision"] == Decimal(1) and decision["outcome"] == meta["state"]
                and decision["report_payload_sha256"] == meta["payload_sha256"]
                and receipt["published"] is False and receipt["dispatch_enabled"] is False)
    require(meta["schema_version"] == SCHEMA)
    require(meta["payload_sha256"] == hashlib.sha256(payload_text.encode("utf-8")).hexdigest())
    for name in ("created_at", "updated_at"):
        require(isinstance(meta[name], str) and datetime.fromisoformat(meta[name]).utcoffset() == timedelta(0))
    identity = meta["request"]
    keys(identity, (*BOUNDARIES, "contract_version", "source_file_sha256", "policy_version",
                    "report_schema_version", "source_time_interpretation"))
    require(identity["contract_version"] == "report-request-v1" and identity["report_schema_version"] == SCHEMA)
    require(identity["source_file_sha256"] == SOURCE_HASH and identity["policy_version"] == "v1")
    require(identity["source_time_interpretation"] == "Europe/London-assumed")
    start, end, cutoff = (source_time(identity[key]) for key in BOUNDARIES)
    require(datetime(2009, 12, 1, 7, 45) <= start - timedelta(days=7) < start < end <= cutoff
            <= datetime(2011, 12, 9, 12, 50, 0, 1) and end - start <= timedelta(days=31))
    keys(report, ("schema_version", "comparison_rule", "relative_change_formula",
                  "source_time_interpretation", "current_period", "prior_period", "changes"))
    require(report["schema_version"] == SCHEMA and report["source_time_interpretation"] == "naive workbook time")
    require(report["comparison_rule"] == "same-window-seven-calendar-days-earlier")
    require(report["relative_change_formula"] == "(current-prior)/abs(prior)")
    for period_name, shift in (("current_period", 0), ("prior_period", 7)):
        period = report[period_name]
        keys(period, (*BOUNDARIES, "schema_version", "source_file_sha256", "policy_version", "kpis", "quality"))
        require(period["schema_version"] == "deterministic-period-report-v1")
        require(period["source_file_sha256"] == SOURCE_HASH and period["policy_version"] == "v1")
        for key, expected in zip(BOUNDARIES, (start - timedelta(days=shift), end - timedelta(days=shift), cutoff)):
            require(source_time(period[key]) == expected)
        keys(period["kpis"], KPIS)
        for key, (_, kind) in KPIS.items():
            number(period["kpis"][key], count=kind == "count", nullable=key in NULLABLE)
        quality = period["quality"]
        keys(quality, ("flagged_source_rows", "finding_rows", "finding_rows_by_code"))
        number(quality["flagged_source_rows"], count=True)
        number(quality["finding_rows"], count=True)
        keys(quality["finding_rows_by_code"], CODES)
        for value in quality["finding_rows_by_code"].values():
            number(value, count=True)
        require(quality["flagged_source_rows"] <= period["kpis"]["period_source_rows"])
        require(quality["flagged_source_rows"] <= quality["finding_rows"])
        require(sum(quality["finding_rows_by_code"].values()) == quality["finding_rows"])
    keys(report["changes"], METRICS)
    for key in METRICS:
        change = report["changes"][key]
        keys(change, ("current_value", "prior_value", "absolute_change", "relative_change", "relative_change_status"))
        for name in ("current_value", "prior_value", "absolute_change", "relative_change"):
            number(change[name], nullable=name == "relative_change")
        current, prior = (report[name]["kpis"][key] for name in ("current_period", "prior_period"))
        require(change["current_value"] == current and change["prior_value"] == prior)
        with localcontext() as context:
            context.prec = 128
            require(change["absolute_change"] == current - prior)
        require(change["relative_change_status"] == ("zero_baseline" if prior == 0 else "available"))
        require((change["relative_change"] is None) == (prior == 0))
    events = meta["audit_events"]
    require(isinstance(events, list) and len(events) == 2)
    require({event["event_type"] for event in events} == {"request_received", "revision_created"})
    for event in events:
        keys(event, ("event_id", "event_type", "revision", "occurred_at", "actor"))
        number(event["revision"], count=True, nullable=event["event_type"] == "request_received")
        require(str(UUID(event["event_id"])) == event["event_id"] and event["actor"] == "local-service-v1")
        require(event["revision"] == (None if event["event_type"] == "request_received" else Decimal(1)))
        require(datetime.fromisoformat(event["occurred_at"]).utcoffset() == timedelta(0))
    return meta, report


def display(value, kind, signed=False):
    if value is None:
        return "Not available (zero denominator)"
    with localcontext() as context:
        context.prec = 128
        shown = value * 100 if kind == "percent" else value
        places = Decimal(1) if kind == "count" else Decimal("0.01")
        shown = shown.quantize(places, rounding=ROUND_HALF_UP)
        if shown == 0:
            shown = abs(shown)  # Never display negative zero.
        prefix = "+" if signed and shown > 0 else ""
        text = prefix + format(shown, ",.0f" if kind == "count" else ",.2f")
        return text + (" GBP" if kind == "money" else "%" if kind == "percent" else "")


def e(value):
    return escape(str(value), quote=True)


def cell(value, kind, signed=False, null_label=None):
    shown = null_label if value is None and null_label else display(value, kind, signed)
    exact = "null" if value is None else str(value)
    return '<td><span class="value">' + e(shown) + '</span><span class="exact">SQL: ' + e(exact) + '</span></td>'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th scope="col">' + e(h) + '</th>' for h in headers) + \
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def render_preview(metadata_text, payload_text, case_id, revision=1):
    meta, report = validate(metadata_text, payload_text, case_id, revision)
    current, prior = report["current_period"], report["prior_period"]
    rows = []
    for key in METRICS:
        label, kind = KPIS[key]
        change = report["changes"][key]
        rows.append('<tr><th scope="row">' + e(label) + '</th>' + cell(change["current_value"], kind) +
                    cell(change["prior_value"], kind) + cell(change["absolute_change"], kind, True) +
                    cell(change["relative_change"], "percent", True, "Not available (zero baseline)") + '</tr>')
    comparison = table(("Metric", "Current", "Prior", "Absolute change", "Relative change"), rows)
    all_kpis = table(("Metric", "Current", "Prior"), [
        '<tr><th scope="row">' + e(label) + '</th>' + cell(current["kpis"][key], kind) +
        cell(prior["kpis"][key], kind) + '</tr>' for key, (label, kind) in KPIS.items()])
    quality_rows = []
    for key, label in (("flagged_source_rows", "Distinct flagged source rows"), ("finding_rows", "All findings")):
        quality_rows.append('<tr><th scope="row">' + label + '</th>' + cell(current["quality"][key], "count") +
                            cell(prior["quality"][key], "count") + '</tr>')
    for code in CODES:
        quality_rows.append('<tr><th scope="row"><code>' + e(code) + '</code></th>' +
                            cell(current["quality"]["finding_rows_by_code"][code], "count") +
                            cell(prior["quality"]["finding_rows_by_code"][code], "count") + '</tr>')
    quality = table(("Quality measure / code", "Current", "Prior"), quality_rows)
    items = [("Case / revision", f'{meta["case_id"]} / 1'),
             ("State", f'{meta["state"]}; approved={str(meta["approved"]).lower()}; published=false'),
             ("Current [start, end)", current["period_start_inclusive"] + " / " + current["period_end_exclusive"]),
             ("Prior [start, end)", prior["period_start_inclusive"] + " / " + prior["period_end_exclusive"]),
             ("Exclusive source cutoff", current["source_as_of_exclusive"]),
             ("Source", "UCI Online Retail II / online_retail_II.xlsx"), ("Source SHA-256", SOURCE_HASH),
             ("Stored JSON SHA-256", meta["payload_sha256"]), ("Schema / policy", SCHEMA + " / v1"),
             ("Case created / updated (UTC)", meta["created_at"] + " / " + meta["updated_at"])]
    provenance = '<dl>' + ''.join('<dt>' + e(label) + '</dt><dd>' + e(value) + '</dd>' for label, value in items) + '</dl>'
    audits = '<ul>' + ''.join('<li>' + e(event["event_type"] + " / " + event["event_id"] + " / " +
                                      event["occurred_at"] + " / " + event["actor"]) + '</li>' for event in meta["audit_events"]) + '</ul>'
    reviewed = meta["state"] in ("approved", "rejected")
    label = (meta["state"].upper()+" · UNPUBLISHED" if reviewed else "UNAPPROVED DRAFT")+" · AI DISABLED"
    receipt_section = ''
    if reviewed:
        receipt_section = '<section><h2>Stored owner decision</h2><pre>'+e(meta["review_receipt"]["canonical_payload_text"])
        receipt_section += '</pre><p>Decision SHA-256: '+e(meta["review_receipt"]["decision_sha256"])
        receipt_section += '</p><p>Publication is disabled. Viewing never renews authorization.</p></section>'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{e(CSP)}"><meta name="referrer" content="no-referrer">
<title>{e(meta["state"])} retail report · revision 1</title><style>{CSS}</style></head><body><main>
<header><div class="eyebrow">Retail Analytics Automation / local review preview</div>
<h1>Deterministic retail report</h1><span class="status">{e(label)}</span>
<p>Read-only inspection of stored revision 1. Viewing records no decision and does not publish or renew authorization.</p></header>
<section><h2>Six headline comparisons</h2><p class="muted">Same source-clock window seven calendar days earlier.
Relative change = (current − prior) / abs(prior). A change is not a causal explanation.</p>{comparison}</section>
<section><h2>Source, period and immutable identity</h2>{provenance}
<p>Source timestamps are naive workbook time. Europe/London is an explicit assumption, not a source fact.
Periods are half-open; both share the exclusive source cutoff. Displayed boundaries are not UTC timestamps.</p></section>
<section><h2>All 20 KPI fields</h2>{all_kpis}
<p class="muted">Missing Customer ID does not exclude valid sales. Other adjustments, zero-quantity and invalid rows are excluded from accepted sales/net sales and disclosed above.
Net recorded sales = accepted sales − cancellation magnitude. Customer coverage is identified sale rows / all sale rows;
active customers count distinct known IDs. Average invoice value = sales / sales invoice count.</p></section>
<section><h2>Data quality</h2>{quality}
<p>Finding codes overlap: their sum counts findings, not distinct rows. A zero means no such finding among the selected canonical rows,
not perfect source quality. Undated rows cannot enter this timestamp-bounded report. Period quality codes are SQL-checked,
but have not been independently recounted from the workbook.</p></section>
<section><h2>Interpretation and display limits</h2><ul>
<li>Historical recorded sales are a revenue proxy, not audited revenue, profit or cash flow. Cancellations use their recorded date;
the cancellation-to-sales ratio is not a matched-order physical-return probability.</li>
<li>Canonical selection uses the older worksheet before 2010-12-01 and the newer worksheet thereafter, after exact overlap guards.
All physical rows and original data remain preserved; identical-valued rows are not automatically removed.</li>
<li>A bounded window is not a claim of complete-day coverage, equal trading exposure or seasonality adjustment.
Full-file integrity guards inspect later source rows. Document/outcome as-of isolation is not implemented.</li>
<li>Display policy {DISPLAY_POLICY}: Decimal ROUND_HALF_UP to 2 decimal places for GBP and percentages; integral counts.
Percentages multiply the stored SQL fraction by 100. Signed changes retain their direction; zero baselines show no percentage.
The SQL line below each value retains stored precision (not an infinitely exact rational result). Null is never replaced by zero.</li>
<li>The SHA-256 identifies the exact stored JSON bytes, not this HTML projection or an approved action payload.
Opening or saving this private preview records no human decision and does not publish the report.</li></ul></section>
{receipt_section}<section><h2>Existing service audit events</h2>{audits}<p class="muted">Service events only; owner decisions, if any, are shown separately above.</p>
<details><summary>Exact stored JSON text (escaped, unchanged)</summary><pre>{e(payload_text)}</pre></details></section>
<footer>Local deterministic preview · no JavaScript, remote assets, credentials or model calls.</footer>
</main></body></html>'''
