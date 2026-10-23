import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import analyze_etfs as app


class AnalyzerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.today = pd.Timestamp("2026-10-23")
        cls.adjusted, cls.close = app.demo_prices(cls.today)

    def test_weights_and_stock_limits(self):
        for index, weights in enumerate(app.PORTFOLIOS.values()):
            self.assertAlmostEqual(sum(weights.values()), 1)
            self.assertTrue(all(w >= 0 for w in weights.values()))
            equities = sum(weights[t] for t in ("VTI", "VUG", "VXUS"))
            self.assertAlmostEqual(equities, [0.25, 0.45, 0][index])

    def test_allocation_does_not_overspend(self):
        prices = pd.Series({ticker: 123.45 for ticker in app.ASSETS})
        for weights in app.PORTFOLIOS.values():
            rows, cash = app.allocate(10000, weights, prices)
            self.assertGreaterEqual(cash, 0)
            self.assertAlmostEqual(sum(r["target_usd"] for r in rows), 10000)
            self.assertAlmostEqual(sum(r["whole_share_cost_usd"] for r in rows) + cash, 10000)
            self.assertTrue(all(r["whole_shares"] >= 0 for r in rows))

    def test_bad_allocation_inputs(self):
        weights = next(iter(app.PORTFOLIOS.values()))
        for amount in (-1, 0, float("nan"), float("inf")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                app.allocate(amount, weights, self.close.iloc[-1])
        with self.assertRaises(ValueError):
            app.allocate(10000, {t: 0 for t in app.ASSETS}, self.close.iloc[-1])
        invalid_prices = self.close.iloc[-1].copy()
        invalid_prices["VTI"] = 0
        with self.assertRaises(ValueError):
            app.allocate(10000, weights, invalid_prices)

    def test_drawdown_includes_starting_capital(self):
        metrics = app.historical_metrics(pd.Series([-0.20, 0.10, 0.10]), 2)
        self.assertAlmostEqual(metrics["historical_monthly_max_drawdown"], -0.20)
        self.assertAlmostEqual(metrics["historical_horizon_worst_return"], -0.12)
        self.assertEqual(metrics["overlapping_historical_windows"], 2)
        self.assertAlmostEqual(metrics["historical_horizon_loss_frequency"], 0.5)

    def test_constant_returns(self):
        metrics = app.historical_metrics(pd.Series([0.01] * 36), 24)
        self.assertAlmostEqual(metrics["historical_annualized_return"], 1.01 ** 12 - 1)
        self.assertAlmostEqual(metrics["historical_annualized_volatility"], 0)
        self.assertEqual(metrics["historical_monthly_max_drawdown"], 0)
        self.assertEqual(metrics["historical_horizon_loss_frequency"], 0)

    def test_monthly_returns_exclude_current_month(self):
        returns = app.monthly_returns(self.adjusted, self.today)
        self.assertEqual(returns.index[-1], pd.Timestamp("2026-09-30"))
        self.assertFalse(returns.isna().any().any())
        with self.assertRaises(ValueError):
            app.monthly_returns(self.adjusted.iloc[-100:], self.today)

    def test_missing_fund_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            app.validate_prices(self.adjusted.drop(columns="VTI"), self.close, self.today)

    def test_partial_missing_prices_rejected(self):
        bad = self.adjusted.copy()
        bad.iloc[-1, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            app.validate_prices(bad, self.close, self.today)

    def test_zero_negative_and_infinite_prices_rejected(self):
        for value in (0, -10, np.inf):
            bad = self.adjusted.copy()
            bad.iloc[-2, 0] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Invalid"):
                app.validate_prices(bad, self.close, self.today)

    def test_stale_and_short_prices_rejected(self):
        with self.assertRaisesRegex(ValueError, "Stale"):
            app.validate_prices(self.adjusted.iloc[:-10], self.close.iloc[:-10], self.today)
        with self.assertRaisesRegex(ValueError, "five years"):
            app.validate_prices(self.adjusted.iloc[-100:], self.close.iloc[-100:], self.today)

    def test_daily_gaps_rejected(self):
        bad = self.adjusted.drop(self.adjusted.index[100:120])
        close = self.close.drop(self.close.index[100:120])
        with self.assertRaisesRegex(ValueError, "gap"):
            app.validate_prices(bad, close, self.today)

    def test_today_bar_excluded(self):
        extra = pd.DataFrame([self.adjusted.iloc[-1]], index=[self.today])
        a = pd.concat([self.adjusted, extra])
        c = pd.concat([self.close, extra])
        clean, _ = app.validate_prices(a, c, self.today)
        self.assertLess(clean.index[-1], self.today)

    def test_mismatched_dates_rejected(self):
        with self.assertRaisesRegex(ValueError, "dates do not match"):
            app.validate_prices(self.adjusted.iloc[:-1], self.close, self.today)

    def test_duplicate_dates_rejected(self):
        duplicate = pd.concat([self.adjusted, self.adjusted.iloc[[-1]]])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            app.validate_prices(duplicate, self.close, self.today)

    def test_joint_bootstrap_reproducible_and_preserves_blocks(self):
        base = np.arange(20, dtype=float)
        monthly = pd.DataFrame({"a": base, "b": base * 2})
        first = app.bootstrap(monthly, 24, 100, 42)
        np.testing.assert_array_equal(first, app.bootstrap(monthly, 24, 100, 42))
        self.assertEqual(first.shape, (100, 24, 2))
        np.testing.assert_array_equal(first[:, :, 1], first[:, :, 0] * 2)
        blocks = first[:, :, 0].reshape(100, 8, 3)
        np.testing.assert_array_equal(np.diff(blocks, axis=2), np.ones((100, 8, 2)))

    def test_constant_bootstrap_terminal_value(self):
        data = pd.DataFrame(np.full((60, 5), 0.01), columns=list(app.ASSETS))
        sample = app.bootstrap(data, 24, 100, 1)
        weights = np.array(list(next(iter(app.PORTFOLIOS.values())).values()))
        terminals = 10000 * np.prod(1 + sample @ weights, axis=1)
        np.testing.assert_allclose(terminals, 10000 * 1.01 ** 24)

    def test_download_failure_does_not_use_demo(self):
        with patch("yfinance.download", return_value=pd.DataFrame()), \
                patch("market_data.time.sleep"), \
                patch.object(app, "demo_prices") as demo:
            with self.assertRaisesRegex(ValueError, "download failed"):
                app.download_prices(self.today)
            demo.assert_not_called()

    def test_complete_analysis_and_exports(self):
        result = app.analyze(self.adjusted, self.close, 10000, 2, 100, 42, self.today, True)
        self.assertIn("SYNTHETIC", result["mode"])
        self.assertEqual(len(result["portfolios"]), 3)
        for portfolio in result["portfolios"]:
            self.assertLessEqual(portfolio["scenario_05_usd"], portfolio["scenario_median_usd"])
            self.assertLessEqual(portfolio["scenario_median_usd"], portfolio["scenario_95_usd"])
            self.assertTrue(0 <= portfolio["simulated_loss_frequency"] <= 1)
        self.assertAlmostEqual(result["portfolios"][0]["hypothetical_stress_value_usd"], 8950)
        self.assertAlmostEqual(result["portfolios"][1]["hypothetical_stress_value_usd"], 8200)
        with tempfile.TemporaryDirectory() as temp:
            report = app.write_report(result, Path(temp))
            content = report.read_text(encoding="utf-8")
            self.assertIn("SYNTHETIC DATA", content)
            self.assertIn("not a worst case", content)
            parsed = json.loads((Path(temp) / "analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed["investment_usd"], 10000)
            for name in ("portfolio_comparison.csv", "allocations.csv", "etf_history.csv"):
                self.assertGreater(len(pd.read_csv(Path(temp) / name)), 0)

    def test_cli_rejects_invalid_investments(self):
        for amount in ("nan", "inf", "-1", "0"):
            with self.subTest(amount=amount), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    app.main(["--amount", amount])
                self.assertEqual(exc.exception.code, 2)

    def test_html_escaping(self):
        self.assertIn("&lt;script&gt;", app.table(["x"], [["<script>"]]))


if __name__ == "__main__":
    unittest.main()
