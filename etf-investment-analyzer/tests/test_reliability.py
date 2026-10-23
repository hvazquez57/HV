import argparse
import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import call, patch

import numpy as np
import pandas as pd
import yfinance as yf

import analyze_etfs as app
import market_data as data
import report_store as store

PROJECT = Path(app.__file__).parent


def arguments(**overrides):
    values = dict(amount=None, years=None, simulations=100, seed=None, demo=False, cached=None)
    values.update(overrides)
    return argparse.Namespace(**values)


class ReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.today = pd.Timestamp("2026-10-23")
        cls.adjusted, cls.close = app.demo_prices(cls.today)
        cls.raw = pd.concat({"Adj Close": cls.adjusted, "Close": cls.close}, axis=1)
        # Offline fixtures exercise the live pipeline; no network call occurs.
        with patch("market_data.download_prices", return_value=(cls.adjusted, cls.close, 1)):
            cls.result, _, _ = app.prepare_analysis(arguments(amount=12345, seed=17), cls.today)

    def publish(self, root, result=None, render=None):
        return store.publish_run(
            copy.deepcopy(result or self.result), self.adjusted, self.close,
            Path(root), render or app.write_report, PROJECT,
        )

    def test_holiday_weekend_and_special_closure_calendar(self):
        dates = data.session_dates("2025-01-01", "2025-01-13")
        for day in ("2025-01-01", "2025-01-04", "2025-01-05", "2025-01-09"):
            self.assertNotIn(pd.Timestamp(day), dates)
        self.assertIn(pd.Timestamp("2025-01-10"), dates)
        self.assertEqual(data.latest_session(pd.Timestamp("2026-07-06")), pd.Timestamp("2026-07-02"))
        schedule = data.calendar().schedule("2026-11-27", "2026-11-27")
        self.assertEqual(schedule.iloc[0]["market_close"].hour, 18)  # 13:00 New York.

    def test_one_missing_session_is_rejected(self):
        bad = self.adjusted.drop(self.adjusted.index[100])
        bad_close = self.close.drop(self.close.index[100])
        with self.assertRaisesRegex(ValueError, "Missing trading sessions"):
            app.validate_prices(bad, bad_close, self.today)

    def test_requested_start_truncation_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing trading sessions"):
            app.validate_prices(
                self.adjusted.iloc[1:], self.close.iloc[1:], self.today,
                requested_start=self.today - pd.DateOffset(years=10),
            )

    def test_missing_latest_session_is_stale(self):
        with self.assertRaisesRegex(ValueError, "Stale"):
            app.validate_prices(self.adjusted.iloc[:-1], self.close.iloc[:-1], self.today)

    def test_off_calendar_price_rejected(self):
        extra = pd.DataFrame([self.adjusted.iloc[-1]], index=[pd.Timestamp("2026-10-18")])
        with self.assertRaisesRegex(ValueError, "Off-calendar"):
            app.validate_prices(
                pd.concat([self.adjusted, extra]), pd.concat([self.close, extra]), self.today,
            )

    def test_intraday_and_null_dates_rejected(self):
        for date in (pd.Timestamp("2026-10-22 12:00"), pd.NaT):
            bad = self.adjusted.copy()
            dates = list(bad.index)
            dates[-1] = date
            bad.index = pd.DatetimeIndex(dates)
            with self.subTest(date=date), self.assertRaisesRegex(ValueError, "daily dates"):
                app.validate_prices(bad, self.close, self.today)

    def test_entire_missing_session_row_not_silently_removed(self):
        bad, close = self.adjusted.copy(), self.close.copy()
        bad.iloc[100] = np.nan
        close.iloc[100] = np.nan
        with self.assertRaisesRegex(ValueError, "Missing trading sessions"):
            app.validate_prices(bad, close, self.today)

    def test_duplicate_columns_rejected(self):
        bad = pd.concat([self.adjusted, self.adjusted[["VTI"]]], axis=1)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            app.validate_prices(bad, self.close, self.today)

    def test_rate_limit_then_timeout_then_success(self):
        from yfinance.exceptions import YFRateLimitError

        previous = yf.config.network.retries
        with patch("yfinance.download", side_effect=[YFRateLimitError(), TimeoutError(), self.raw]) as fetch, \
                patch("market_data.time.sleep") as sleep, \
                contextlib.redirect_stderr(io.StringIO()):
            adjusted, close, count = data.download_prices(self.today, app.ASSETS)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])
        self.assertEqual(yf.config.network.retries, previous)
        pd.testing.assert_frame_equal(adjusted, self.adjusted)
        pd.testing.assert_frame_equal(close, self.close)

    def test_partial_response_retry_recovers(self):
        bad = self.raw.copy()
        bad.loc[bad.index[-1], ("Adj Close", "VTI")] = np.nan
        with patch("yfinance.download", side_effect=[bad, self.raw]) as fetch, \
                patch("market_data.time.sleep"), contextlib.redirect_stderr(io.StringIO()):
            _, _, attempts = data.download_prices(self.today, app.ASSETS)
        self.assertEqual(attempts, 2)
        self.assertEqual(fetch.call_count, 2)

    def test_retry_budget_and_no_implicit_fallback(self):
        previous = yf.config.network.retries
        with patch("yfinance.download", return_value=pd.DataFrame()) as fetch, \
                patch("market_data.time.sleep") as sleep, \
                patch("report_store.load_snapshot") as cache, \
                patch.object(app, "demo_prices") as demo, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "after 3 attempt"):
                data.download_prices(self.today, app.ASSETS)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        cache.assert_not_called()
        demo.assert_not_called()
        self.assertEqual(yf.config.network.retries, previous)

    def test_invalid_schema_and_values_are_not_retried(self):
        bad_values = self.raw.copy()
        bad_values.iloc[0, 0] = -1
        for raw in (self.adjusted, bad_values):
            with self.subTest(schema=type(raw.columns)), \
                    patch("yfinance.download", return_value=raw) as fetch, \
                    patch("market_data.time.sleep") as sleep:
                with self.assertRaises(ValueError):
                    data.download_prices(self.today, app.ASSETS)
                self.assertEqual(fetch.call_count, 1)
                sleep.assert_not_called()

    def test_http_retry_classification(self):
        for status, expected in ((400, False), (401, False), (404, False), (429, True), (503, True)):
            error = RuntimeError()
            error.response = argparse.Namespace(status_code=status)
            self.assertEqual(data.is_transient(error), expected)
        self.assertFalse(data.is_transient(ValueError("invalid ticker")))

    def test_publication_manifest_pointer_and_exact_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            report = self.publish(temp)
            pointer = json.loads((Path(temp) / "latest.json").read_text())
            self.assertEqual(report, Path(temp) / pointer["report"])
            self.assertEqual(report.parent.name, pointer["run_id"])
            loaded = store.load_snapshot(report.parent)
            np.testing.assert_array_equal(loaded.adjusted.to_numpy(), self.adjusted.to_numpy())
            self.assertEqual(loaded.manifest["settings"]["seed"], 17)
            env = loaded.manifest["environment"]
            self.assertIn("numpy", {name.lower() for name in env["dependencies"]})
            self.assertIn("dirty", env["git"])
            self.assertTrue(set(store.SOURCE_FILES) <= set(env["source_code_sha256"]))
            self.assertIsNotNone(env["constraints_sha256"])
            self.assertEqual(set(loaded.manifest["artifacts"]), set(store.ARTIFACTS))
            self.assertIn("12345", (report.parent / "analysis.json").read_text())

    def test_two_runs_and_concurrent_runs_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            with ThreadPoolExecutor(max_workers=2) as executor:
                reports = list(executor.map(lambda _: self.publish(temp), range(2)))
            self.assertNotEqual(reports[0].parent, reports[1].parent)
            for report in reports:
                store.load_snapshot(report.parent)
            pointer = json.loads((Path(temp) / "latest.json").read_text())
            self.assertIn(Path(temp) / pointer["report"], reports)
            self.assertFalse(list(Path(temp).glob(".pending-*")))

    def test_cached_replay_freezes_cutoff_settings_and_numeric_results(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.publish(temp).parent
            with patch("market_data.download_prices") as fetch, patch.object(app, "demo_prices") as demo:
                replay, adjusted, close = app.prepare_analysis(
                    arguments(cached=source, simulations=None), pd.Timestamp("2027-02-03"),
                )
            fetch.assert_not_called()
            demo.assert_not_called()
            self.assertEqual(replay["portfolios"], self.result["portfolios"])
            self.assertEqual(replay["etf_history"], self.result["etf_history"])
            self.assertEqual(replay["reproducibility"]["settings"]["amount"], 12345)
            self.assertEqual(replay["reproducibility"]["settings"]["seed"], 17)
            self.assertEqual(replay["reproducibility"]["analysis_cutoff"], "2026-10-23")
            self.assertIn("CACHED", replay["mode"])
            self.assertTrue(any("STALE CACHED" in warning for warning in replay["data_warnings"]))
            output = Path(temp) / "replayed"
            report = store.publish_run(replay, adjusted, close, output, app.write_report, PROJECT)
            self.assertIn("STALE CACHED DATA", report.read_text(encoding="utf-8"))
            second = store.load_snapshot(report.parent)
            self.assertEqual(second.manifest["mode"], "cached")
            original = store.load_snapshot(source).manifest["run_id"]
            self.assertEqual(second.manifest["source_snapshot"]["origin_run_id"], original)

    def test_cache_override_is_explicit_and_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.publish(temp).parent
            replay, _, _ = app.prepare_analysis(
                arguments(cached=source, amount=5000, seed=9), self.today,
            )
            self.assertEqual(replay["investment_usd"], 5000)
            self.assertEqual(replay["seed"], 9)
            self.assertEqual(replay["reproducibility"]["settings"]["amount"], 5000)

    def test_dependency_difference_warns_and_model_difference_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.publish(temp).parent
            with patch("report_store.dependency_versions", return_value={"numpy": "different"}):
                replay, _, _ = app.prepare_analysis(arguments(cached=source), self.today)
            self.assertTrue(any("dependency versions differ" in text for text in replay["data_warnings"]))
        changed = copy.deepcopy(self.result)
        changed["reproducibility"]["model"]["version"] = 999
        with tempfile.TemporaryDirectory() as temp:
            source = self.publish(temp, result=changed).parent
            with self.assertRaisesRegex(ValueError, "model definitions"):
                app.prepare_analysis(arguments(cached=source), self.today)

    def test_current_cache_is_still_not_live(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.publish(temp).parent
            replay, _, _ = app.prepare_analysis(arguments(cached=source), self.today)
            self.assertIn("NOT LIVE", replay["mode"])
            self.assertTrue(any("NOT LIVE" in message for message in replay["data_warnings"]))
            self.assertFalse(any("STALE CACHED" in message for message in replay["data_warnings"]))

    def test_legacy_and_synthetic_caches_rejected(self):
        with self.assertRaisesRegex(ValueError, "Legacy"):
            store.load_snapshot(PROJECT / "reports")
        with tempfile.TemporaryDirectory() as temp:
            result, adjusted, close = app.prepare_analysis(arguments(demo=True), self.today)
            report = store.publish_run(result, adjusted, close, Path(temp), app.write_report, PROJECT)
            with self.assertRaisesRegex(ValueError, "synthetic"):
                store.load_snapshot(report.parent)

    def test_corrupted_input_and_missing_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.publish(temp).parent
            (source / "adjusted_prices.csv").write_text("corrupted", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity"):
                store.load_snapshot(source)
        with tempfile.TemporaryDirectory() as temp:
            source = self.publish(temp).parent
            (source / "allocations.csv").unlink()
            with self.assertRaisesRegex(ValueError, "integrity"):
                store.load_snapshot(source)

    def test_manifest_status_and_provenance_mismatch_rejected(self):
        for field, value in (
            ("status", "pending"), ("analysis_cutoff", "2026-10-24"),
            ("environment", None), ("source_snapshot", True), ("schema_version", 999),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                source = self.publish(temp).parent
                path = source / "manifest.json"
                manifest = json.loads(path.read_text())
                manifest[field] = value
                path.write_bytes(store.json_bytes(manifest))
                with self.assertRaises(ValueError):
                    store.load_snapshot(source)

    def test_write_rename_and_pointer_failures_preserve_previous_run(self):
        def fail_render(result, target):
            (target / "analysis.json").write_text("partial", encoding="utf-8")
            raise OSError("injected renderer write failure")

        for phase in ("render", "rename", "pointer", "pointer-write", "input", "manifest"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                first = self.publish(temp)
                before = {
                    str(path.relative_to(temp)): path.read_bytes()
                    for path in Path(temp).rglob("*") if path.is_file()
                }
                original_write = Path.write_bytes

                def fail_write(path, value):
                    if phase == "input" and path.name == "adjusted_prices.csv":
                        raise OSError("injected input failure")
                    if phase == "manifest" and path.name == "manifest.json":
                        raise OSError("injected manifest failure")
                    if phase == "pointer-write" and path.name.startswith(".latest-"):
                        raise OSError("injected pointer write failure")
                    return original_write(path, value)

                with contextlib.ExitStack() as stack:
                    if phase == "rename":
                        stack.enter_context(patch.object(Path, "rename", side_effect=OSError("rename")))
                    if phase == "pointer":
                        stack.enter_context(patch("report_store.os.replace", side_effect=OSError("pointer")))
                    if phase in {"input", "manifest", "pointer-write"}:
                        stack.enter_context(patch.object(Path, "write_bytes", autospec=True, side_effect=fail_write))
                    with self.assertRaises(OSError):
                        self.publish(temp, render=fail_render if phase == "render" else None)
                after = {
                    str(path.relative_to(temp)): path.read_bytes()
                    for path in Path(temp).rglob("*") if path.is_file()
                }
                self.assertEqual(before, after)
                self.assertTrue(first.is_file())
                self.assertEqual(len(list(Path(temp).iterdir())), 2)

    def test_incomplete_renderer_cannot_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "incomplete"):
                self.publish(temp, render=lambda result, target: None)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_failed_cli_download_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch("market_data.download_prices", side_effect=ValueError("injected download")), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(["--output", temp]), 1)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_failed_cli_write_returns_failure_not_success(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(app, "write_report", side_effect=OSError("injected write")), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(["--demo", "--simulations", "100", "--output", temp]), 1)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_mutually_exclusive_modes_and_invalid_settings(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                app.main(["--demo", "--cached", "somewhere"])
            self.assertEqual(error.exception.code, 2)
        for values in (dict(simulations=99), dict(seed=-1), dict(years=3)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                app.prepare_analysis(arguments(**values), self.today)

    def test_git_unavailable_is_explicit(self):
        with patch("report_store.shutil.which", return_value="nonexistent-git"), \
                patch("report_store.subprocess.run", side_effect=FileNotFoundError()):
            self.assertEqual(
                store.git_metadata(PROJECT),
                {"commit": None, "dirty": None, "available": False},
            )
        with patch("report_store.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            self.assertIsNone(store.git_metadata(PROJECT)["commit"])

    def test_legacy_market_snapshot_financial_regression(self):
        root = PROJECT / "reports"
        original = json.loads((root / "analysis.json").read_text(encoding="utf-8"))
        adjusted, close = [
            pd.read_csv(root / name, index_col="date", parse_dates=True, float_precision="round_trip")
            for name in store.INPUT_FILES
        ]
        app.validate_prices(
            adjusted, close, self.today, requested_start=self.today - pd.DateOffset(years=10),
        )
        current = app.analyze(
            adjusted, close, original["investment_usd"], 2, original["simulations"],
            original["seed"], self.today, False,
        )
        for before, after in zip(original["portfolios"], current["portfolios"]):
            for key, value in before.items():
                if isinstance(value, (float, int)):
                    self.assertAlmostEqual(value, after[key], delta=max(1e-8, abs(value) * 1e-10))


if __name__ == "__main__":
    unittest.main()
