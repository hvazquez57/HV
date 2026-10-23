"""Educational USD ETF comparison. No trading, guarantees, or personalized advice."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

ASSETS = {
    "VTI": "Broad US stocks",
    "VUG": "US growth stocks (overlaps VTI)",
    "VXUS": "International stocks",
    "VGSH": "Short-term US Treasury bonds",
    "SHV": "Short US Treasury bills/bonds",
}
PORTFOLIOS = {
    "Conservative growth (25% stocks)": {
        "VTI": 0.15, "VUG": 0.05, "VXUS": 0.05, "VGSH": 0.25, "SHV": 0.50,
    },
    "Moderate growth (45% stocks)": {
        "VTI": 0.25, "VUG": 0.10, "VXUS": 0.10, "VGSH": 0.25, "SHV": 0.30,
    },
    "Treasury reference (not guaranteed)": {
        "VTI": 0.0, "VUG": 0.0, "VXUS": 0.0, "VGSH": 0.0, "SHV": 1.0,
    },
}
# Hypothetical cumulative two-year total returns, not a forecast or worst case.
STRESS = {"VTI": -0.35, "VUG": -0.45, "VXUS": -0.35, "VGSH": -0.05, "SHV": 0.0}
NOTES = [
    "Educational comparison, not personalized investment advice. USD and US-listed "
    "ETFs are assumed. No trades are submitted.",
    "Two years is a short equity horizon. Neither portfolio is guaranteed low risk; "
    "stocks and Treasury ETFs can lose principal. If the money must be available in "
    "full in two years, compare insured deposits or individual Treasuries matched "
    "to that date. An ETF has no fixed redemption value or maturity for your shares.",
    "The portfolios are predefined examples, not optimized recommendations. "
    "The moderate mix takes more equity risk. VUG overlaps VTI; it is a growth tilt, "
    "not independent diversification. No leveraged, inverse, or sector ETFs are used.",
    "Historical returns use dividend/split-adjusted prices as a reinvested-distribution "
    "proxy. Fund expenses are already reflected in prices; do not deduct them twice. "
    "Taxes, spreads, commissions and inflation are excluded; figures are nominal USD.",
    "History, rolling results and simulations assume monthly rebalancing to target "
    "weights and fractional holdings. Whole-share orders are only approximate initial "
    "allocations. Rebalancing can incur taxes and costs.",
    "Simulation jointly resamples three-month blocks of historical monthly ETF "
    "returns, preserving within-block co-movement. It assumes the past distribution "
    "is relevant; yields, valuations and regimes can change. Percentiles and loss "
    "frequencies are model outputs, NOT calibrated future probabilities. Losses "
    "outside the displayed range are possible.",
    "Overlapping historical two-year windows are not independent observations. "
    "Historical maximum drawdown is not a future loss limit. Monthly observations "
    "can miss deeper intramonth losses.",
    "The stress illustration applies the disclosed cumulative asset shocks to initial "
    "weights without rebalancing. It is separate from the resampling model, not a "
    "worst case, and not a prediction.",
    "Live data is from Yahoo Finance via yfinance, an unofficial research tool subject "
    "to provider terms and possible errors or delays. Today's incomplete daily bar "
    "is excluded. Share estimates use the last completed session's unadjusted close, "
    "not an executable quote. Verify prices and fund documents before acting.",
    "The ten-year sample may not include all relevant crises. No macroeconomic, "
    "valuation or forward yield model is used. Falling interest rates can lower "
    "future Treasury ETF income; foreign holdings add currency and geopolitical risks.",
]


def validate_prices(
    adjusted: pd.DataFrame,
    close: pd.DataFrame,
    today: pd.Timestamp,
    check_freshness: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reject missing funds, stale series, holes and nonpositive observations."""
    frames = []
    for label, frame in (("adjusted", adjusted), ("close", close)):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"No {label} prices downloaded. Check internet/provider access.")
        missing = set(ASSETS) - set(frame.columns)
        if missing:
            raise ValueError(f"Missing {label} ETF prices: {', '.join(sorted(missing))}")
        data = frame.loc[:, list(ASSETS)].copy()
        data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
        data = data.loc[data.index < today].sort_index()
        if data.index.has_duplicates:
            raise ValueError("Duplicate market dates in price data.")
        # Completely empty rows can represent provider-inserted non-trading dates.
        data = data.dropna(how="all")
        if data.empty or data.isna().any().any():
            raise ValueError(f"Incomplete {label} data; refusing to fill missing ETF prices.")
        if not np.isfinite(data.to_numpy(dtype=float)).all() or (data <= 0).any().any():
            raise ValueError(f"Invalid {label} prices.")
        if check_freshness and (today - data.index[-1]).days > 5:
            raise ValueError(f"Stale {label} prices: latest date {data.index[-1].date()}.")
        frames.append(data)
    if not frames[0].index.equals(frames[1].index):
        raise ValueError("Adjusted and unadjusted price dates do not match.")
    # Require a useful multi-year comparison and enough full two-year windows.
    if len(frames[0]) < 252 * 5:
        raise ValueError("At least five years of common daily history are required.")
    if (frames[0].index.to_series().diff().dt.days.dropna() > 7).any():
        raise ValueError("Unexpected gap longer than seven days in daily history.")
    return frames[0], frames[1]


def download_prices(today: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    import yfinance as yf

    raw = yf.download(
        list(ASSETS),
        start=(today - pd.DateOffset(years=10)).strftime("%Y-%m-%d"),
        end=today.strftime("%Y-%m-%d"),
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
        timeout=30,
        group_by="column",
        multi_level_index=True,
    )
    if raw is None or raw.empty or not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("Market-data download failed. No synthetic fallback was used.")
    if not {"Adj Close", "Close"}.issubset(raw.columns.get_level_values(0)):
        raise ValueError("Provider did not return both adjusted and unadjusted closes.")
    return validate_prices(raw["Adj Close"], raw["Close"], today)


def demo_prices(today: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthetic test data only: never presented as actual market prices."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(today - pd.DateOffset(years=10), today - pd.Timedelta(days=1))
    common = rng.normal(0, 0.009, (len(dates), 1))
    beta = np.array([1.0, 1.2, 0.9, -0.03, 0.0])
    noise = rng.normal(size=(len(dates), 5)) * np.array([0.003, 0.005, 0.005, 0.001, 0.0001])
    drift = np.array([0.00025, 0.0003, 0.00018, 0.00008, 0.00008])
    prices = 100 * np.exp(np.cumsum(common * beta + noise + drift, axis=0))
    frame = pd.DataFrame(prices, index=dates, columns=list(ASSETS))
    return validate_prices(frame, frame.copy(), today)


def monthly_returns(adjusted: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    # Drop current partial month AND first partial month at the sample boundary.
    month_ends = adjusted.resample("ME").last()
    month_ends = month_ends.loc[month_ends.index < today.to_period("M").start_time]
    result = month_ends.iloc[1:].pct_change(fill_method=None).dropna()
    if len(result) < 60:
        raise ValueError("At least 60 complete monthly return observations are required.")
    return result


def historical_metrics(returns: pd.Series, horizon_months: int) -> dict:
    values = returns.to_numpy(dtype=float)
    wealth = np.r_[1.0, np.cumprod(1 + values)]
    drawdown = wealth / np.maximum.accumulate(wealth) - 1
    windows = pd.Series(values).add(1).rolling(horizon_months).apply(np.prod, raw=True) - 1
    windows = windows.dropna()
    if windows.empty:
        raise ValueError("History is shorter than the requested investment horizon.")
    return {
        "historical_annualized_return": float(wealth[-1] ** (12 / len(values)) - 1),
        "historical_annualized_volatility": float(np.std(values, ddof=1) * np.sqrt(12)),
        "historical_monthly_max_drawdown": float(drawdown.min()),
        "historical_horizon_worst_return": float(windows.min()),
        "historical_horizon_loss_frequency": float((windows < 0).mean()),
        "overlapping_historical_windows": int(len(windows)),
    }


def bootstrap(
    monthly: pd.DataFrame,
    months: int,
    simulations: int,
    seed: int,
) -> np.ndarray:
    """Return jointly sampled assets, shape (simulation, month, asset)."""
    if months < 1 or simulations < 1 or len(monthly) < 3:
        raise ValueError("Positive horizon, simulation count and three observations required.")
    rng = np.random.default_rng(seed)
    block = 3
    starts = rng.integers(0, len(monthly) - block + 1,
                          size=(simulations, (months + block - 1) // block))
    indexes = (starts[:, :, None] + np.arange(block)).reshape(simulations, -1)[:, :months]
    return monthly.to_numpy()[indexes]


def allocate(amount: float, weights: dict, prices: pd.Series) -> tuple[list[dict], float]:
    if not np.isfinite(amount) or amount <= 0:
        raise ValueError("Investment must be a finite positive USD amount.")
    if set(weights) != set(ASSETS) or any(not np.isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError("Weights must be finite, nonnegative and cover the ETF universe.")
    if not np.isclose(sum(weights.values()), 1):
        raise ValueError("Portfolio weights must sum to one.")
    rows = []
    for symbol in ASSETS:
        price = float(prices[symbol])
        if not np.isfinite(price) or price <= 0:
            raise ValueError(f"Invalid allocation price for {symbol}.")
        target = amount * weights[symbol]
        shares = int(np.floor(target / price))
        rows.append({
            "ticker": symbol, "description": ASSETS[symbol], "weight": weights[symbol],
            "target_usd": round(target, 2), "last_close_usd": price,
            "whole_shares": shares, "whole_share_cost_usd": round(shares * price, 2),
        })
    cash = round(amount - sum(row["whole_share_cost_usd"] for row in rows), 2)
    return rows, cash


def analyze(
    adjusted: pd.DataFrame, close: pd.DataFrame, amount: float,
    years: int, simulations: int, seed: int, today: pd.Timestamp, demo: bool,
) -> dict:
    monthly = monthly_returns(adjusted, today)
    months = years * 12
    sampled = bootstrap(monthly, months, simulations, seed)
    result = {
        "mode": "DEMO - SYNTHETIC DATA, NOT MARKET ANALYSIS" if demo else "LIVE MARKET DATA",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "latest_price_date": str(close.index[-1].date()),
        "price_history_start": str(adjusted.index[0].date()),
        "monthly_return_start": str(monthly.index[0].date()),
        "monthly_return_end": str(monthly.index[-1].date()),
        "investment_usd": amount, "horizon_years": years,
        "simulations": simulations, "seed": seed,
        "source": "Synthetic demo" if demo else "Yahoo Finance via yfinance",
        "stress_asset_total_returns": STRESS,
        "notes": NOTES,
        "etf_history": [],
        "portfolios": [],
    }
    for ticker in ASSETS:
        result["etf_history"].append({
            "ticker": ticker, "description": ASSETS[ticker],
            **historical_metrics(monthly[ticker], months),
        })
    for name, weights in PORTFOLIOS.items():
        w = np.array([weights[t] for t in ASSETS])
        historical = monthly @ w
        simulated_returns = sampled @ w
        terminals = amount * np.prod(1 + simulated_returns, axis=1)
        q05, q50, q95 = np.quantile(terminals, [0.05, 0.5, 0.95])
        allocations, cash = allocate(amount, weights, close.iloc[-1])
        stress_return = sum(weights[t] * STRESS[t] for t in ASSETS)
        result["portfolios"].append({
            "name": name, **historical_metrics(historical, months),
            "scenario_05_usd": float(q05), "scenario_median_usd": float(q50),
            "scenario_95_usd": float(q95),
            "simulated_loss_frequency": float(np.mean(terminals < amount)),
            "hypothetical_stress_return": stress_return,
            "hypothetical_stress_value_usd": amount * (1 + stress_return),
            "allocations": allocations, "uninvested_cash_usd": cash,
        })
    return result


def money(value: float) -> str:
    return f"${value:,.2f}"


def percent(value: float) -> str:
    return f"{value:.1%}"


def table(headers: list[str], rows: list[list[str]]) -> str:
    def cells(tag: str, values: list[str]) -> str:
        return "".join(f"<{tag}>{escape(str(value))}</{tag}>" for value in values)
    return ("<div class='scroll'><table><thead><tr>" + cells("th", headers)
            + "</tr></thead><tbody>"
            + "".join("<tr>" + cells("td", row) + "</tr>" for row in rows)
            + "</tbody></table></div>")


def write_report(result: dict, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    (output / "analysis.json").write_text(
        json.dumps(result, indent=2, allow_nan=False), encoding="utf-8",
    )
    portfolios = result["portfolios"]
    pd.DataFrame([{k: v for k, v in p.items() if k != "allocations"} for p in portfolios]).to_csv(
        output / "portfolio_comparison.csv", index=False,
    )
    pd.DataFrame([
        {"portfolio": p["name"], **row} for p in portfolios for row in p["allocations"]
    ]).to_csv(output / "allocations.csv", index=False)
    pd.DataFrame(result["etf_history"]).to_csv(output / "etf_history.csv", index=False)
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>ETF two-year investment comparison</title><style>",
        "body{font:16px/1.6 system-ui,sans-serif;max-width:1200px;margin:36px auto;"
        "padding:0 24px;color:#16283b;background:#f6f8fb}h1,h2{line-height:1.2}"
        "table{border-collapse:collapse;width:100%;background:white;font-size:14px}"
        "th,td{padding:12px;text-align:left;border-bottom:1px solid #dce2ea}"
        ".scroll{overflow-x:auto}th{background:#e5edf7}.warning{padding:18px;"
        "background:#fff0ce;border-left:5px solid #b36b00}li{margin:12px 0}"
        "section{margin:30px 0}small{color:#45586b}</style></head><body>",
        "<h1>ETF investment comparison</h1>",
        f"<p class='warning'><strong>{escape(result['mode'])}</strong><br>"
        "Growth and low risk can conflict over two years. Capital is not guaranteed. "
        "These are illustrative choices, not a buy recommendation.</p>",
        f"<p>Investment: <strong>{money(result['investment_usd'])} USD</strong> | "
        f"Horizon: {result['horizon_years']} years | Latest completed price session: "
        f"{escape(result['latest_price_date'])}<br>"
        f"Source: {escape(result['source'])} | Generated: {escape(result['generated_utc'])}</p>",
        "<h2>Historical comparison (not a forecast)</h2>",
        f"<p>Complete monthly returns: {escape(result['monthly_return_start'])} to "
        f"{escape(result['monthly_return_end'])}. Monthly rebalancing assumed.</p>",
        table(
            ["Example portfolio", "Annualized growth", "Annualized volatility",
             "Max monthly drawdown", f"Worst {result['horizon_years']}-year return",
             "Historical window loss frequency"],
            [[p["name"], percent(p["historical_annualized_return"]),
              percent(p["historical_annualized_volatility"]),
              percent(p["historical_monthly_max_drawdown"]),
              percent(p["historical_horizon_worst_return"]),
              percent(p["historical_horizon_loss_frequency"])] for p in portfolios],
        ),
        "<h2>Model-dependent future scenarios</h2>",
        f"<p>{result['simulations']:,} joint three-month-block bootstrap paths. "
        "These are not promised returns or reliable future probabilities. "
        "The 5th percentile is not a worst case.</p>",
        table(
            ["Portfolio", "5th percentile", "Median", "95th percentile",
             "Simulated loss frequency", "Separate hypothetical stress value"],
            [[p["name"], money(p["scenario_05_usd"]), money(p["scenario_median_usd"]),
              money(p["scenario_95_usd"]), percent(p["simulated_loss_frequency"]),
              money(p["hypothetical_stress_value_usd"])] for p in portfolios],
        ),
        "<p>Stress assumptions (cumulative asset total returns): "
        + escape(", ".join(f"{t}: {percent(v)}" for t, v in STRESS.items())) + ".</p>",
    ]
    for p in portfolios:
        parts.extend([
            f"<section><h2>{escape(p['name'])}: initial allocation</h2>",
            table(
                ["ETF", "Exposure", "Weight", "Fractional-share target",
                 "Last close", "Whole shares", "Whole-share cost"],
                [[row["ticker"], row["description"], percent(row["weight"]),
                  money(row["target_usd"]), money(row["last_close_usd"]),
                  str(row["whole_shares"]), money(row["whole_share_cost_usd"])]
                 for row in p["allocations"] if row["weight"] > 0],
            ),
            f"<p>Residual cash with whole shares: {money(p['uninvested_cash_usd'])}. "
            "Do not combine allocations from the different example portfolios.</p></section>",
        ])
    parts.extend([
        "<h2>ETF historical risk</h2>",
        table(
            ["ETF", "Exposure", "Annualized growth", "Annualized volatility",
             "Maximum monthly drawdown"],
            [[e["ticker"], e["description"], percent(e["historical_annualized_return"]),
              percent(e["historical_annualized_volatility"]),
              percent(e["historical_monthly_max_drawdown"])] for e in result["etf_history"]],
        ),
        "<h2>Methodology and limitations</h2><ul>",
        *[f"<li>{escape(note)}</li>" for note in result["notes"]],
        "</ul><p><small>Review your liquidity needs, emergency reserves, tax situation, "
        "and ability to tolerate losses before choosing investments.</small></p></body></html>",
    ])
    report = output / "report.html"
    report.write_text("".join(parts), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amount", type=float, default=10000, help="Initial investment in USD.")
    parser.add_argument("--years", type=int, choices=[2], default=2, help="Two-year investment horizon.")
    parser.add_argument("--simulations", type=int, default=10000, help="Bootstrap paths, 100-50000.")
    parser.add_argument("--seed", type=int, default=42, help="Nonnegative reproducible random seed.")
    parser.add_argument("--output", type=Path, default=None, help="Report output directory.")
    parser.add_argument("--demo", action="store_true", help="Use clearly labeled synthetic data.")
    args = parser.parse_args(argv)
    if not np.isfinite(args.amount) or args.amount <= 0:
        parser.error("--amount must be finite and positive.")
    if not 100 <= args.simulations <= 50000:
        parser.error("--simulations must be between 100 and 50000.")
    if args.seed < 0:
        parser.error("--seed must be nonnegative.")
    # Use the exchange's calendar date even when run from another time zone.
    today = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    try:
        print("Loading SYNTHETIC DEMO data..." if args.demo else "Downloading completed ETF sessions...")
        adjusted, close = demo_prices(today) if args.demo else download_prices(today)
        result = analyze(adjusted, close, args.amount, args.years,
                         args.simulations, args.seed, today, args.demo)
        default_output = Path(__file__).parent / ("demo_reports" if args.demo else "reports")
        output = (args.output or default_output).expanduser().resolve()
        report = write_report(result, output)
        adjusted.to_csv(output / "adjusted_prices.csv", index_label="date")
        close.to_csv(output / "unadjusted_closes.csv", index_label="date")
        print(f"\n{result['mode']}\nLatest price date: {result['latest_price_date']}")
        for p in result["portfolios"]:
            print(f"\n{p['name']}")
            print(f"  Model 5th/median/95th: {money(p['scenario_05_usd'])} / "
                  f"{money(p['scenario_median_usd'])} / {money(p['scenario_95_usd'])}")
            print(f"  Model loss frequency (not a forecast): {percent(p['simulated_loss_frequency'])}")
            print(f"  Hypothetical stress value: {money(p['hypothetical_stress_value_usd'])}")
        print(f"\nReport: {report}\nEducational examples only. Principal can be lost.")
        return 0
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f"Analysis failed: {exc}\nNo fabricated market analysis was substituted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
