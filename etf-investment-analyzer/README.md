# ETF Investment Analyzer

A Python command-line tool that compares illustrative ETF portfolios for a **$10,000 USD investment over two years**. It downloads historical market data, reports portfolio risk, estimates initial allocations, and generates model-dependent two-year scenarios.

**This is an educational research tool, not personalized financial advice or a trading system.** Growth and low risk can conflict over a two-year horizon. Neither stocks nor Treasury ETFs guarantee your principal.

## Requirements

- Python 3.10 or newer; Python 3.13 was used for initial testing.
- Windows PowerShell for the optional `run.ps1` launcher.
- Internet access for installing dependencies and downloading live data. Once dependencies are installed, demo mode and unit tests do not require market-data access.
- A browser to view the self-contained HTML report.

The runtime dependencies are NumPy, pandas, yfinance, and pandas-market-calendars. Ruff is an optional development dependency. No brokerage account or API key is required.

## Setup and quick start

The application lives in the `etf-investment-analyzer` subfolder of the `HV` repository. Git metadata and repository-wide ignore rules remain at the repository root.

Open PowerShell in the application directory before using the commands below. For this installation:

```powershell
Set-Location "F:\Users\Owner\etf-investment-analyzer\etf-investment-analyzer"
```

After cloning `HV` elsewhere, enter its `etf-investment-analyzer` subfolder instead. The launcher creates a new local `.venv` beside `run.ps1` if needed; it does not reuse the environment left at the repository root by the earlier layout.

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

The launcher records hashes of `requirements.txt`, applicable constraints, and the Python series; it reinstalls dependencies when those inputs change. On Windows x86-64 with Python 3.13, it applies `constraints-windows-py313.txt`, pinning tested runtime and optional development dependency versions. These constraints are environment-specific, not a universal lock. Other Python versions use bounded requirements and need separate validation.

NumPy is constrained below 2.4 alongside pandas 2.x to avoid the observed generic-timedelta deprecation. Warnings are not suppressed; tests treat deprecation warnings as errors.

### Manual setup

Use a working Python 3.10+ executable:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\analyze_etfs.py
$Latest = Get-Content .\reports\latest.json -Raw | ConvertFrom-Json
Start-Process (Join-Path .\reports $Latest.report)
```

Virtual-environment activation is not required. If `python` opens the Microsoft Store or is not found, use the full path to your installed Python executable for the first command.

For the tested Windows x86-64/Python 3.13 environment, replace the dependency-install command with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints-windows-py313.txt
```

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

Replay a newly generated live run without downloading prices:

```powershell
$Latest = Get-Content .\reports\latest.json -Raw | ConvertFrom-Json
$SourceRun = Join-Path (Resolve-Path .\reports).Path $Latest.run_id
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Cached $SourceRun -OpenReport
```

### Python command line

Use Python directly for simulation settings or a custom output directory:

```powershell
.\.venv\Scripts\python.exe .\analyze_etfs.py --help
.\.venv\Scripts\python.exe .\analyze_etfs.py --amount 10000 --years 2 --simulations 20000 --seed 42 --output .\reports-custom
.\.venv\Scripts\python.exe .\analyze_etfs.py --demo
.\.venv\Scripts\python.exe .\analyze_etfs.py --cached $SourceRun --output .\cached_reports
```

Options:

- `--amount`: finite positive initial investment in USD; default `10000` for live/demo or the source amount for cached replay.
- `--years`: currently accepts **only `2`**.
- `--simulations`: bootstrap paths, from `100` to `50000`; default `10000` or the source setting in cached mode.
- `--seed`: nonnegative simulation seed; default `42` or the source seed in cached mode.
- `--output`: root for immutable run directories; defaults to `reports`, `demo_reports`, or `cached_reports` beside the program according to mode.
- `--demo`: explicitly use synthetic data, labeled as such in the report and JSON.
- `--cached RUN_DIRECTORY`: replay a complete manifest-bearing market snapshot without network access; mutually exclusive with `--demo`.

The launcher exposes `-Amount`, `-Demo`, `-Cached`, `-Output`, `-Test`, and `-OpenReport`; other options require the Python command line. Cached mode inherits the source amount unless `-Amount` is explicitly supplied.

## Generated files

Each successful run writes a unique UTC timestamp/UUID-named subdirectory under the selected output root, containing:

- `report.html`: browser-readable comparison, scenarios, allocations, and limitations.
- `analysis.json`: structured results, source/mode, dates, settings, and methodology notes.
- `portfolio_comparison.csv`: portfolio-level historical and scenario metrics.
- `allocations.csv`: target weights, target dollars, last closes, whole-share counts, and estimated costs.
- `etf_history.csv`: historical metrics for each ETF.
- `adjusted_prices.csv`: downloaded, validated dividend/split-adjusted prices used for return calculations.
- `unadjusted_closes.csv`: validated non-dividend-adjusted closes used for initial share estimates.
- `manifest.json`: completion status, input/artifact hashes, source provenance, analysis settings, model definitions, environment versions, source-code hashes, and Git revision/dirty state when available.

The output root also contains `latest.json`, pointing to the last successfully published run's HTML and manifest. `-OpenReport` follows this pointer only after a successful invocation and checks that it is newly written. Do not use the legacy fixed `reports/report.html` as the result of a new run.

All artifacts are staged privately on the same filesystem. Only after every write succeeds is the directory renamed into its final location; the latest pointer is then replaced atomically. Handled write/publication failures clean up this invocation's artifacts and leave previous complete runs and their pointer unchanged. Failure returns nonzero without a success message. Abrupt termination can leave unreferenced staging data; this is not a guarantee against power loss or filesystem failure.

Live, cached, and demo runs have separate default roots. Previously committed files directly under `reports/` are legacy snapshots and remain unchanged. Existing tracked snapshots stay versioned; new run folders, default cached/demo outputs, virtual environments, and caches are ignored by Git. A custom output folder is not automatically ignored.

### Cached replay and reproducibility

Select the actual run directory containing `manifest.json`, not the output root or `latest.json`. The loader verifies all seven artifact hashes, cross-checks manifest/analysis provenance, and rejects missing, modified, incomplete, unsupported, or synthetic snapshots. Legacy reports have no verified manifest and cannot be used as caches; generate a new live run first.

Replay preserves the source analysis cutoff, historical month selection, portfolio/stress definitions, amount, simulation count, and seed unless supported numeric options are explicitly overridden. Historical sessions are validated against that recorded cutoff, not today's freshness. Cached reports always say **CACHED / NOT LIVE** and display source dates; missing current sessions add a prominent **STALE CACHED DATA** warning. A stale snapshot is never silently treated as current.

Source-run identity, source-manifest hash, original live-run identity, and settings are retained for chained replays. Inputs use round-trip floating-point CSV serialization. The same inputs/settings with the same source and compatible software reproduce financial metrics; timestamps, run IDs, and current-age warnings intentionally differ. Source-code or core dependency-version changes produce replay warnings; model/calendar-definition changes are rejected. Retain the corresponding source code and environment, particularly for dirty runs.

The manifest stores Python/platform and installed package versions, Git commit/dirty state when available (explicit nulls otherwise), application-source hashes, constraints hash, input hashes, model definitions, cutoff dates, and random seeds. It does not capture credentials or environment-variable values. Hashes detect accidental changes; they are not signatures or independent proof of vendor data accuracy.

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

The calendar date is determined in `America/New_York`. All bars dated today or later are excluded, even after close. NYSE sessions from pandas-market-calendars provide the shared US-equity holiday/closure calendar for this fixed ETF universe, including early-close dates as valid daily sessions. This is a calendar proxy, not an independent market-data source.

Validation requires all five ETFs and:

- Matching adjusted/unadjusted date indexes with no duplicate dates.
- Finite, strictly positive prices and no partially missing rows.
- A latest observation equal to the last eligible trading session strictly before the cutoff.
- At least 1,260 daily rows, used as an approximate five-year minimum.
- Every expected session from the requested ten-year start through the eligible final session, including leading, interior, and trailing sessions.
- No off-calendar dates, malformed/null daily labels, or non-midnight observations.

Completely empty rows are dropped but still cause rejection when an expected session is left missing. Individual observations are not forward-filled. Calendar rules are packaged locally and may require updates for newly announced or corrected closures.

Live downloads allow at most three application-level attempts with 1- and 2-second backoff and a 30-second timeout per provider request. Provider-level retries are temporarily disabled to avoid multiplying retry budgets and are restored afterward. Empty/incomplete/missing-session responses and identifiable transient transport/rate-limit errors can be retried; invalid values and schemas fail immediately. The timeout is per request, not a guarantee on the whole multi-ETF operation. Persistent failure returns nonzero and publishes nothing. There is **no automatic cached or synthetic fallback**.

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
.\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe -m ruff check --config pyproject.toml analyze_etfs.py market_data.py report_store.py tests
.\.venv\Scripts\python.exe -m pip check
```

On Windows x86-64/Python 3.13, add `-c constraints-windows-py313.txt` to the development dependency installation. Tests cover the original financial calculations plus holidays, single missing sessions, bounded retries, cached integrity/staleness/frozen-cutoff replay, concurrent publication, unavailable Git metadata, and injected input/render/manifest/rename/pointer failures. They check financial regression against the committed market snapshot. Provider calls are mocked; tests do not need live data.

## Next steps for future enhancements

Item 1 is implemented as described above; items 2-4 remain proposed work, **not currently implemented features**. Keep the $10,000, two-year example available as a regression case.

### 1. Strengthen data reliability and reproducibility

- Implemented NYSE-session validation, including holiday closures, missing/extra sessions, and current-session exclusion.
- Implemented bounded retries and fail-closed behavior with no implicit mode fallback.
- Implemented explicit integrity-checked cached replay with frozen cutoff dates and stale-data warnings.
- Implemented immutable run folders, all-artifact staging, and atomic latest-pointer publication.
- Implemented reproducibility metadata and tested Windows/Python 3.13 constraints; deprecation warnings are tested as errors.

Validation: saved inputs/settings reproduce financial metrics; injected download/write/publication failures cannot produce misleading successful reports. Concurrency and preservation of prior outputs are covered offline.

### 2. Make assumptions configurable without weakening safeguards

- Move portfolio definitions and risk limits into a validated configuration file. Require nonnegative weights totaling one and make equity exposure and overlapping holdings explicit.
- Support other investment horizons only after updating history requirements, rolling windows, bootstrap path lengths, stress assumptions, report labels, and tests together. The current CLI continues to accept only two years until this is complete.
- Add optional contributions, withdrawals, rebalancing schedules, transaction costs, inflation assumptions, and residual-cash treatment. Clearly separate fractional target portfolios from whole-share implementations.
- Treat support for other currencies as a separate extension requiring exchange-rate data and explicit reporting-currency assumptions, not just a different currency symbol.

Completion criterion: invalid configurations fail clearly, defaults preserve the existing calculations, and each new assumption is disclosed in both the report and JSON output.

### 3. Expand risk analysis and model validation

- Add daily drawdown analysis with a clearly specified rebalancing convention, plus rolling risk charts and historical crisis-period comparisons where data is available.
- Compare bootstrap block lengths and historical sample periods. Add walk-forward evaluation using only information available at each evaluation date to avoid look-ahead bias.
- Explore separate, dated forward-yield and interest-rate scenarios for Treasury exposures rather than assuming historical average returns describe current income prospects.
- Expand transparent equity, interest-rate, and inflation stress cases, documenting whether shocks are hypothetical or historical and whether rebalancing is assumed.
- Report sensitivity and uncertainty alongside results; do not relabel bootstrap loss frequencies as reliable future probabilities or rank portfolios solely by backtested growth.

Completion criterion: model changes have deterministic regression tests, documented sensitivity results, and limitations explaining where the model can fail.

### 4. Improve the reporting and development experience

- Add accessible charts for historical wealth, drawdowns, portfolio exposures, and terminal-value distributions while retaining the CSV/JSON exports.
- Surface warnings, source dates, allocation differences, and scenario assumptions near the relevant results rather than only in methodology notes.
- Add continuous integration for offline unit tests, Ruff, CLI smoke tests, and report-generation checks. Keep network-dependent provider checks separate from required deterministic tests.
- Test supported Python versions and the Windows launcher, including clean installation from the nested project directory. Consider packaging the CLI to simplify setup.

Completion criterion: a fresh checkout can install, test, and generate a clearly labeled demo report through documented commands without a brokerage account or market-data credentials.

### Suggested implementation order and contribution workflow

With reproducible metadata and safer publication implemented, add CI coverage next, followed by configurable portfolios and model/report improvements in small independent changes.

Before starting an enhancement, synchronize with the latest `main` and create a focused feature branch. Open integration PRs against **`main`**, include tests and methodology/documentation updates, and keep virtual environments, credentials, and caches out of commits. Add generated snapshots only intentionally, documenting settings and data dates.

[PR #1](https://github.com/hvazquez57/HV/pull/1) began as a retrospective review, was retargeted to `main`, and merged the roadmap documentation. Its old feature branch was deleted. Do not target `review/initial-project-baseline` for enhancements. This roadmap adds neither automated trading nor guarantees of investment performance.

## Troubleshooting

- **Python not found:** install Python or use its full executable path; the Microsoft Store alias is not a Python installation.
- **Dependency setup fails:** confirm internet/proxy access and retry `python -m pip install -r requirements.txt` using the virtual-environment Python.
- **Download, missing-data, or stale-data error:** check connectivity, provider availability, and the dates reported. The program deliberately refuses incomplete or stale data rather than filling it. Use `--demo` only to try the interface, not to obtain market analysis.
- **Old report still present:** prior complete runs and legacy reports are deliberately preserved. Use the new path printed on success or the output root's `latest.json`; failed runs do not advance that pointer.
- **Cache rejected:** choose a complete new-format market-data run directory. Missing manifests, hash mismatches, synthetic runs, and unsupported provenance are rejected.
- **Need another horizon, currency, or ETF universe:** these are not supported CLI settings. They require coordinated code, methodology, and test changes; currently `--years` accepts only `2`.
