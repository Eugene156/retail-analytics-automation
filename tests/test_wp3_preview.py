"""Preview projection and ASGI tests; synthetic fixtures are not workbook evidence."""
import copy
from decimal import Decimal
import hashlib
from html import escape
import json
import secrets
import unittest
from uuid import UUID

from api.main import Settings, create_app
from api.preview import CODES, KPIS, METRICS, NULLABLE, SCHEMA, SOURCE_HASH, display, render_preview
from test_wp2_api import FakeCalculator, call

CID = UUID("00000000-0000-0000-0000-000000000033")


def fixture():
    def period(start, end):
        return {"schema_version": "deterministic-period-report-v1", "source_file_sha256": SOURCE_HASH,
                "policy_version": "v1", "period_start_inclusive": start, "period_end_exclusive": end,
                "source_as_of_exclusive": "2011-01-28T10:00:00.000000",
                "kpis": {key: None if key in NULLABLE else 0 for key in KPIS},
                "quality": {"flagged_source_rows": 0, "finding_rows": 0,
                            "finding_rows_by_code": dict.fromkeys(CODES, 0)}}
    current = period("2011-01-28T09:00:00.000000", "2011-01-28T10:00:00.000000")
    prior = period("2011-01-21T09:00:00.000000", "2011-01-21T10:00:00.000000")
    report = {"schema_version": SCHEMA, "comparison_rule": "same-window-seven-calendar-days-earlier",
              "relative_change_formula": "(current-prior)/abs(prior)", "source_time_interpretation": "naive workbook time",
              "current_period": current, "prior_period": prior,
              "changes": {key: {"current_value": 0, "prior_value": 0, "absolute_change": 0,
                                "relative_change": None, "relative_change_status": "zero_baseline"} for key in METRICS}}
    identity = {key: current[key] for key in ("source_file_sha256", "policy_version", "period_start_inclusive",
                                            "period_end_exclusive", "source_as_of_exclusive")}
    identity.update(contract_version="report-request-v1", report_schema_version=SCHEMA,
                    source_time_interpretation="Europe/London-assumed")
    meta = {"case_id": str(CID), "state": "awaiting_approval", "revision": 1, "request": identity,
            "created_at": "2026-10-01T00:00:00+00:00", "updated_at": "2026-10-01T00:00:01+00:00",
            "schema_version": SCHEMA, "approved": False, "published": False,
            "audit_events": [{"event_id": str(UUID(int=i + 1)), "event_type": name,
                              "revision": None if i == 0 else 1, "occurred_at": "2026-10-01T00:00:00+00:00",
                              "actor": "local-service-v1"} for i, name in enumerate(("request_received", "revision_created"))]}
    return meta, report


def encoded(meta, report):
    payload = report if isinstance(report, str) else json.dumps(report)
    meta = copy.deepcopy(meta)
    meta["payload_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    return json.dumps(meta), payload


class RendererTests(unittest.TestCase):
    def test_empty_all_fields_nulls_and_inert_page(self):
        meta, report = fixture()
        metadata, payload = encoded(meta, report)
        page = render_preview(metadata, payload, CID)
        self.assertIn("UNAPPROVED DRAFT", page)
        self.assertIn("AI DISABLED", page)
        self.assertEqual(page.count("Not available (zero baseline)"), 6)
        self.assertEqual(page.count("Not available (zero denominator)"), 6)
        self.assertIn(escape(payload, quote=True), page)
        for key in CODES:
            self.assertIn(key, page)
        for label, _ in KPIS.values():
            self.assertIn(label, page)
        for forbidden in ("<script", "<form", "<iframe", "<img", "href=", "fetch("):
            self.assertNotIn(forbidden, page)

    def test_decimal_rounding_negative_zero_counts_and_percent(self):
        for value, expected in (("1.005", "1.01 GBP"), ("-1.005", "-1.01 GBP"),
                                ("-0.004", "0.00 GBP"), ("123456789012345678901234.995", "123,456,789,012,345,678,901,235.00 GBP")):
            self.assertEqual(display(Decimal(value), "money"), expected)
        self.assertEqual(display(Decimal("0.73293010234875627641"), "percent", True), "+73.29%")
        self.assertEqual(display(Decimal("1001"), "count"), "1,001")
        self.assertEqual(display(Decimal("-661.88"), "money"), "-661.88 GBP")

    def test_stored_precision_and_negative_baseline_not_float(self):
        meta, report = fixture()
        report["current_period"]["kpis"]["net_recorded_sales_gbp"] = 2020.41
        report["prior_period"]["kpis"]["net_recorded_sales_gbp"] = -661.88
        report["changes"]["net_recorded_sales_gbp"] = {
            "current_value": 2020.41, "prior_value": -661.88, "absolute_change": 2682.29,
            "relative_change": "EXACT_NUMBER", "relative_change_status": "available"}
        text = json.dumps(report).replace('"EXACT_NUMBER"', "4.052555750287061098")
        page = render_preview(*encoded(meta, text), CID)
        self.assertIn("+405.26%", page)
        self.assertIn("SQL: 4.052555750287061098", page)
        self.assertIn("-661.88 GBP", page)

    def test_hash_identity_schema_cutoff_quality_and_unknown_data_fail_closed(self):
        original_meta, original_report = fixture()
        mutations = [lambda m, r: m.update(approved=True), lambda m, r: m.update(case_id=str(UUID(int=0))),
                     lambda m, r: m.update(revision=2), lambda m, r: r.update(schema_version="unknown"),
                     lambda m, r: r["current_period"].update(source_file_sha256="0" * 64),
                     lambda m, r: r["prior_period"].update(source_as_of_exclusive="2011-01-21T10:00:00.000000"),
                     lambda m, r: r["current_period"]["quality"].update(finding_rows=1),
                     lambda m, r: r["changes"]["units_sold"].update(absolute_change=1),
                     lambda m, r: r["changes"]["units_sold"].update(relative_change=0),
                     lambda m, r: r["current_period"]["kpis"].update(units_sold=-1),
                     lambda m, r: r.update(description="<script>alert(1)</script>"),
                     lambda m, r: m["audit_events"][0].update(actor="<img src=x onerror=alert(1)>"),
                     lambda m, r: r["current_period"]["kpis"].update(sales_value_gbp=True)]
        for mutation in mutations:
            meta, report = copy.deepcopy(original_meta), copy.deepcopy(original_report)
            mutation(meta, report)
            with self.assertRaises((ValueError, TypeError, KeyError)):
                render_preview(*encoded(meta, report), CID)
        metadata, payload = encoded(original_meta, original_report)
        with self.assertRaises(ValueError):
            render_preview(metadata, payload + " ", CID)

    def test_duplicate_nonfinite_oversized_numbers_and_markup_are_rejected(self):
        meta, report = fixture()
        original = json.dumps(report)
        for text in ('{"schema_version":"bad",' + original[1:], original.replace('"units_sold": 0', '"units_sold": NaN'),
                     original.replace('"units_sold": 0', '"units_sold": 1e999'),
                     original.replace('"units_sold": 0', '"units_sold": ' + '9' * 65),
                     original.replace('"sales_value_gbp": 0', '"sales_value_gbp": "<svg onload=alert(1)>"')):
            with self.assertRaises(ValueError):
                render_preview(*encoded(meta, text), CID)


class Routes(unittest.IsolatedAsyncioTestCase):
    async def test_protected_read_only_html_and_generic_invalid_response(self):
        meta, report = fixture()
        metadata, payload = encoded(meta, report)
        class Store:
            def get(self, cid): return metadata
            def revision(self, cid, revision): return payload
        token = secrets.token_hex(32)
        app = create_app(Settings(token, "unused"), FakeCalculator(), Store())
        path = f"/api/v1/cases/{CID}/revisions/1/preview"
        self.assertEqual((await call(app, "GET", path))[0], 401)
        self.assertEqual((await call(app, "GET", path, token="wrong"))[0], 401)
        status, body, headers = await call(app, "GET", path, token=token)
        self.assertEqual(status, 200)
        self.assertIn(b"UNAPPROVED DRAFT", body)
        self.assertIn((b"cache-control", b"no-store"), headers)
        self.assertIn((b"x-content-type-options", b"nosniff"), headers)
        self.assertTrue(any(k == b"content-security-policy" for k, v in headers))
        self.assertNotIn(token.encode(), body)
        self.assertEqual((await call(app, "POST", path, token=token))[0], 405)
        for revision in ("0", "2", "9" * 60):
            self.assertEqual((await call(app, "GET", path.replace("/1/", f"/{revision}/"), token=token))[0], 404)
        report["schema_version"] = "<script>private hostile data</script>"
        metadata, payload = encoded(meta, report)
        status, body, _ = await call(app, "GET", path, token=token)
        self.assertEqual(status, 409)
        self.assertNotIn(b"hostile", body)


if __name__ == "__main__":
    unittest.main()
