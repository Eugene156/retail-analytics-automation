"""Fast checks for the read-only canonical workbook reconciliation helper."""

from __future__ import annotations

from datetime import datetime
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_wp2_canonical_workbook import (  # noqa: E402
    Bucket, HASH, compare, compare_report, finalize, headline_changes,
    periods_for, prior_periods_for, selected_sheet,
)


class CanonicalWorkbookTests(unittest.TestCase):
    def test_seven_day_baselines_and_same_sheet_guard(self) -> None:
        periods = periods_for(["M02", "M10"])
        priors = prior_periods_for(periods)
        self.assertEqual(priors[0].name, "M02_prior")
        self.assertEqual(priors[0].start, datetime(2011, 1, 21, 9))
        self.assertEqual(priors[0].end, datetime(2011, 1, 21, 10))
        self.assertEqual(priors[1].start, datetime(2010, 12, 25))
        with self.assertRaises(ValueError):
            prior_periods_for(periods_for(["cross_cutover"]))

    def test_changes_with_negative_and_zero_baselines(self) -> None:
        current = dict(finalize(Bucket()), sales_value_gbp=Decimal("20"),
                       net_recorded_sales_gbp=Decimal("15"))
        prior = dict(finalize(Bucket()), sales_value_gbp=Decimal("10"),
                     net_recorded_sales_gbp=Decimal("-10"))
        changes = headline_changes(current, prior)
        self.assertEqual(len(changes), 6)
        self.assertEqual(changes["sales_value_gbp"]["absolute_change"], Decimal("10"))
        self.assertEqual(changes["sales_value_gbp"]["relative_change"], Fraction(1))
        self.assertEqual(changes["net_recorded_sales_gbp"]["relative_change"], Fraction(5, 2))
        self.assertEqual(changes["units_sold"]["relative_change_status"], "zero_baseline")
        self.assertIsNone(changes["units_sold"]["relative_change"])
        prior["sales_value_gbp"] = Decimal(0)
        self.assertIsNone(headline_changes(current, prior)["sales_value_gbp"]["relative_change"])

    def test_report_reconciliation_rejects_changed_values_and_provenance(self) -> None:
        period = periods_for(["M02"])[0]
        prior_period = prior_periods_for([period])[0]
        current = finalize(Bucket())
        prior = finalize(Bucket())

        def nested(selected):
            return {
                "schema_version": "deterministic-period-report-v1",
                "source_file_sha256": HASH, "policy_version": "v1",
                "period_start_inclusive": selected.start.isoformat(timespec="microseconds"),
                "period_end_exclusive": selected.end.isoformat(timespec="microseconds"),
                "source_as_of_exclusive": period.end.isoformat(timespec="microseconds"),
                "kpis": dict(current),
            }

        observed = {
            "schema_version": "deterministic-comparison-report-v1",
            "comparison_rule": "same-window-seven-calendar-days-earlier",
            "relative_change_formula": "(current-prior)/abs(prior)",
            "source_time_interpretation": "naive workbook time",
            "current_period": nested(period), "prior_period": nested(prior_period),
            "changes": headline_changes(current, prior),
        }
        compare_report(period, prior_period, current, prior, observed)
        mutations = [
            ("prior_period", "source_as_of_exclusive", "wrong-cutoff"),
            ("current_period", "source_file_sha256", "wrong-hash"),
            ("prior_period", "period_start_inclusive", "wrong-start"),
        ]
        for section, key, value in mutations:
            changed = deepcopy(observed)
            changed[section][key] = value
            with self.assertRaises(ValueError):
                compare_report(period, prior_period, current, prior, changed)
        changed = deepcopy(observed)
        changed["prior_period"]["kpis"]["sales_value_gbp"] = Decimal("0.01")
        with self.assertRaises(ValueError):
            compare_report(period, prior_period, current, prior, changed)
        for field, value in (("absolute_change", 1), ("relative_change", 0),
                             ("relative_change_status", "available")):
            changed = deepcopy(observed)
            changed["changes"]["sales_value_gbp"][field] = value
            with self.assertRaises(ValueError):
                compare_report(period, prior_period, current, prior, changed)

        # Finite SQL division is compared against exact rational expectations.
        current["sales_value_gbp"] = Decimal("20")
        prior["sales_value_gbp"] = Decimal("10")
        current["sales_invoice_count"] = 4
        prior["sales_invoice_count"] = 3
        observed["current_period"]["kpis"] = current
        observed["prior_period"]["kpis"] = prior
        observed["changes"] = headline_changes(current, prior)
        for change in observed["changes"].values():
            relative = change["relative_change"]
            if relative is not None:
                change["relative_change"] = Decimal(relative.numerator) / Decimal(relative.denominator)
        compare_report(period, prior_period, current, prior, observed)
        observed["changes"]["sales_invoice_count"]["relative_change"] += Decimal("0.01")
        with self.assertRaises(ValueError):
            compare_report(period, prior_period, current, prior, observed)

    def test_manifest_periods_and_cutover(self) -> None:
        periods = periods_for(["cross_cutover", "M02", "M07", "M10"])
        self.assertEqual([p.name for p in periods], ["cross_cutover", "M02", "M07", "M10"])
        self.assertEqual(periods[1].start, datetime(2011, 1, 28, 9))
        self.assertFalse(selected_sheet("Year 2009-2010", datetime(2010, 12, 1)))
        self.assertTrue(selected_sheet("Year 2010-2011", datetime(2010, 12, 1)))
        with self.assertRaises(ValueError):
            periods_for(["M02", "M02"])
        with self.assertRaises(ValueError):
            periods_for(["M99"])

    def test_empty_period_and_exact_mismatch(self) -> None:
        empty = finalize(Bucket())
        self.assertEqual(len(empty), 20)
        self.assertEqual(empty["period_source_rows"], 0)
        self.assertEqual(empty["sales_value_gbp"], Decimal(0))
        self.assertIsNone(empty["average_sales_invoice_value_exact"])
        self.assertIsNone(empty["customer_coverage_exact"])
        self.assertIsNone(empty["cancellation_to_sales_value_ratio_exact"])
        compare(empty, empty)
        changed = dict(empty, invalid_rows=1)
        with self.assertRaises(ValueError):
            compare(empty, changed)


if __name__ == "__main__":
    unittest.main()
