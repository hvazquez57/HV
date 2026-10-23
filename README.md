# ETF Investment Analyzer

A Python command-line tool that compares illustrative ETF portfolios for a **$10,000 USD investment over two years**. It downloads historical market data, reports portfolio risk, estimates initial allocations, and generates model-dependent two-year scenarios.

**This is an educational research tool, not personalized financial advice or a trading system.** Growth and low risk can conflict over a two-year horizon. Neither stocks nor Treasury ETFs guarantee your principal.

## Requirements

- Python 3.10 or newer; Python 3.13 was used for initial testing.
- Windows PowerShell for the optional `run.ps1` launcher.
- Internet access for installing dependencies and downloading live data. Once dependencies are installed, demo mode and unit tests do not require market-data access.
- A browser to view the self-contained HTML report.

The runtime dependencies are NumPy, pandas, and yfinance. Ruff is an optional development dependency. No brokerage account or API key is required.

## Setup and quick start

Open PowerShell in the project directory. For this installation:

```powershell
Set-Location "F:\Users\Owner\etf-investment-analyzer"
```

If Python is not installed, install it from [python.org](https://www.python.org/downloads/) or use:

```powershell
winget install --id Python.Python.3.13 --exact --scope user
```

Run the live analysis and open its report:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -OpenReport
```

The launcher creates `.venv`, installs `requirements.txt`, and runs the analyzer. It checks standard user-local Python 3.12, 3.13, and 3.14 locations, then `python` on PATH, excluding Microsoft Store execution aliases. For other installation locations, put a working `python` executable on PATH or use the manual setup below.

The execution-policy option applies to this PowerShell process; it does not permanently change system policy. Only run scripts you trust.

The launcher records a hash of `requirements.txt` and reinstalls dependencies when that file changes. Dependency versions are bounded, not locked exactly; different installation dates may resolve different versions.

### Manual setup

Use a working Python 3.10+ executable:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\analyze_etfs.py
Start-Process .\reports\report.html
```

Virtual-environment activation is not required. If `python` opens the Microsoft Store or is not found, use the full path to your installed Python executable for the first command.

## Usage

### PowerShell launcher

```powershell
# Live data; default $10,000 investment.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1

# Change the USD investment amount and open the report.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Amount 15000 -OpenReport

# Explicit synthetic demo; does not download market prices.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Demo -OpenReport

# Run the offline unit tests instead of generating a report.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Test
```

### Python command line

Use Python directly for simulation settings or a custom output directory:

```powershell
.\.venv\Scripts\python.exe .\analyze_etfs.py --help
.\.venv\Scripts\python.exe .\analyze_etfs.py --amount 10000 --years 2 --simulations 20000 --seed 42 --output .\reports-custom
.\.venv\Scripts\python.exe .\analyze_etfs.py --demo
```

Options:

- `--amount`: finite positive initial investment in USD; default `10000`.
- `--years`: currently accepts **only `2`**.
- `--simulations`: number of bootstrap paths, from `100` to `50000`; default `10000`.
- `--seed`: nonnegative simulation random seed; default `42`.
- `--output`: destination directory; defaults to `reports` beside the program, or `demo_reports` in demo mode.
- `--demo`: explicitly use synthetic data, labeled as such in the report and JSON.

The launcher exposes `-Amount`, `-Demo`, `-Test`, and `-OpenReport`; other options require the Python command line.

## Generated files

Each successful run writes:

- `report.html`: browser-readable comparison, scenarios, allocations, and limitations.
- `analysis.json`: structured results, source/mode, dates, settings, and methodology notes.
- `portfolio_comparison.csv`: portfolio-level historical and scenario metrics.
- `allocations.csv`: target weights, target dollars, last closes, whole-share counts, and estimated costs.
- `etf_history.csv`: historical metrics for each ETF.
- `adjusted_prices.csv`: downloaded, validated dividend/split-adjusted prices used for return calculations.
- `unadjusted_closes.csv`: validated non-dividend-adjusted closes used for initial share estimates.

Live and demo runs use separate default directories. Reusing an output directory overwrites files with the same names; it does not create an archive. An unsuccessful run may leave an older report in place. Always check the console result, report mode, generation timestamp, and latest price date. Do not mix demo and live runs in a shared custom output directory.

`.venv`, default report folders, and Python caches are excluded from Git. A custom output folder is not automatically ignored.

## Portfolio examples

The examples use US-listed ETFs and assume USD:

- **VTI:** broad US equities.
- **VUG:** US growth equities; overlaps VTI rather than providing independent diversification.
- **VXUS:** international equities, with currency and geopolitical exposure.
- **VGSH:** short-term US Treasury bonds.
- **SHV:** short US Treasury bills/bonds.

Fixed target allocations:

- **Conservative growth — 25% equities:** VTI 15%, VUG 5%, VXUS 5%, VGSH 25%, SHV 50%.
- **Moderate growth — 45% equities:** VTI 25%, VUG 10%, VXUS 10%, VGSH 25%, SHV 30%.
- **Treasury reference:** SHV 100%; this is not a guaranteed cash account.

These are predefined comparisons, not portfolios selected by maximizing historical returns. There is no automatic suitability assessment or buy recommendation. No leveraged, inverse, or sector ETFs are used.

## Methodology

### Market data and validation

Live mode requests ten years of daily Yahoo Finance history through [yfinance](https://ranaroussi.github.io/yfinance/), using `auto_adjust=False` to obtain both `Adj Close` and `Close`.

The calendar date is determined in `America/New_York`. All bars dated today or later are excluded, even if today's session has already closed. This avoids using an incomplete current-session bar.

Validation requires all five ETFs and:

- Matching adjusted/unadjusted date indexes with no duplicate dates.
- Finite, strictly positive prices and no partially missing rows.
- A latest observation no more than five calendar days old.
- At least 1,260 daily rows, used as an approximate five-year minimum.
- No gap between retained daily rows longer than seven calendar days.

Completely empty rows are dropped; missing individual ETF observations are not forward-filled. These checks are basic safeguards, not a full exchange-calendar audit or independent verification of vendor data. A live-data failure does **not** trigger a synthetic fallback.

### Monthly returns and historical risk

Adjusted daily prices are resampled to the last available observation in each calendar month. The current partial month and first boundary month-end are discarded before calculating percentage changes. At least 60 monthly return observations are required.

For each ETF, monthly return is `r[t] = P[t] / P[t-1] - 1`. For a portfolio, `r_portfolio[t] = sum(weight[i] * r[i,t])`. This assumes fractional holdings and rebalancing to target weights at the start of each monthly return period.

Historical metrics include:

- **Annualized growth:** `product(1 + r[t]) ** (12 / number_of_months) - 1`.
- **Annualized volatility:** sample standard deviation of monthly returns multiplied by `sqrt(12)`.
- **Maximum monthly drawdown:** the lowest wealth-to-prior-peak ratio minus one, including initial capital in the wealth series.
- **Worst two-year return:** the minimum compounded return across overlapping 24-month windows.
- **Historical loss frequency:** the fraction of those windows with a negative return.

Overlapping windows are not independent observations. Month-end drawdowns can miss deeper intramonth losses.

### Two-year scenario generation

The program uses a joint moving-block bootstrap:

1. Construct all possible contiguous three-month blocks from historical monthly asset returns.
2. Sample block starting positions uniformly with replacement.
3. Use the same sampled rows for all ETFs, retaining cross-asset co-movement within each block.
4. Concatenate eight blocks to create each 24-month path.
5. Apply target portfolio weights each month and compound from the initial investment.

The same sampled paths are used for every portfolio. The report shows terminal-value 5th, 50th, and 95th percentiles and the fraction of paths ending below the initial investment.

The seed makes sampling reproducible for the same input data and compatible software versions. Live results can change as data updates or vendor history is revised. Demo price generation uses its own fixed seed of `42`; `--seed` controls scenario sampling, not demo price generation.

**These percentiles and loss frequencies are model outputs, not calibrated forecasts or guarantees.** Resampling assumes the historical distribution is relevant. It does not preserve long-run regimes across independently sampled block boundaries or model future valuations, interest rates, economic conditions, or unprecedented crises.

### Separate stress illustration

A separate hypothetical two-year shock assumes cumulative total returns of:

- VTI: -35%.
- VUG: -45%.
- VXUS: -35%.
- VGSH: -5%.
- SHV: 0%.

The stress return is the initial-weighted sum of these asset shocks, without rebalancing. For $10,000, the resulting values are $8,950 for the conservative mix, $8,200 for the moderate mix, and $10,000 for the Treasury reference.

This illustration is not derived from the bootstrap. It is neither a prediction nor a worst case. In particular, SHV's assumed zero stress return is not a promise of principal protection.

### Allocation estimates

Fractional-share target dollars equal initial investment times target weight. Whole-share counts are rounded down using the latest completed-session `Close`; costs are displayed to cents, and leftover dollars are reported as residual cash.

The `Close` field is not dividend-adjusted; Yahoo may already adjust it for splits. These are not executable quotes. The whole-share allocation can differ from target weights, particularly for small investments.

Historical and simulated performance use fully invested fractional targets, not the rounded whole-share holdings or residual cash. Dividends are treated as reinvested through adjusted prices. There are no later contributions or withdrawals.

### Important limitations

- Fund expenses are already reflected in prices and are not deducted a second time.
- Taxes, bid/ask spreads, trading commissions, and inflation are excluded.
- Treasury ETFs have changing prices and income; they do not mature at a fixed value for your shares.
- The sample does not cover every market crisis, and historical losses do not cap future losses.
- The tool does not model forward yields, valuation, fundamentals, news, or currency hedging.
- Yahoo Finance data can be delayed, incomplete, or revised. yfinance is unofficial and not endorsed by Yahoo; review [its usage notice](https://github.com/ranaroussi/yfinance#readme) and the provider's data-use terms.
- If preserving the full amount at a fixed two-year date is essential, compare appropriately insured deposits or individual Treasuries matched to that date rather than treating equity or bond ETFs as guaranteed substitutes.

## Development and testing

Install development dependencies after creating the virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe -m ruff check --config pyproject.toml analyze_etfs.py tests
```

The unit tests cover allocation math, weights, historical metrics, data rejection, current-session exclusion, joint bootstrap behavior, report exports, CLI validation, and HTML escaping. The download-failure test mocks the provider; tests do not require live market data.

## Troubleshooting

- **Python not found:** install Python or use its full executable path; the Microsoft Store alias is not a Python installation.
- **Dependency setup fails:** confirm internet/proxy access and retry `python -m pip install -r requirements.txt` using the virtual-environment Python.
- **Download, missing-data, or stale-data error:** check connectivity, provider availability, and the dates reported. The program deliberately refuses incomplete or stale data rather than filling it. Use `--demo` only to try the interface, not to obtain market analysis.
- **Old report still present:** failed runs do not remove previous reports. Verify the run succeeded and inspect report timestamps.
- **Need another horizon, currency, or ETF universe:** these are not supported CLI settings. They require coordinated code, methodology, and test changes; currently `--years` accepts only `2`.
