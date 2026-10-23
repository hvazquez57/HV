"""Strict US-equity session validation and bounded Yahoo download attempts."""

from __future__ import annotations

import sys
import time
from functools import lru_cache

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

CALENDAR_NAME = "NYSE"
MAX_ATTEMPTS = 3


class DataUnavailableError(ValueError):
    """A provider returned no/partial data; a bounded retry may recover it."""


@lru_cache(maxsize=1)
def calendar():
    return mcal.get_calendar(CALENDAR_NAME)


def session_dates(start, end) -> pd.DatetimeIndex:
    if pd.Timestamp(start) > pd.Timestamp(end):
        return pd.DatetimeIndex([])
    return calendar().valid_days(
        start_date=str(pd.Timestamp(start).date()),
        end_date=str(pd.Timestamp(end).date()),
        tz=None,
    )


def latest_session(cutoff: pd.Timestamp) -> pd.Timestamp:
    sessions = session_dates(cutoff - pd.DateOffset(months=1), cutoff - pd.Timedelta(days=1))
    if sessions.empty:
        raise ValueError("Calendar has no eligible session before the analysis cutoff.")
    return sessions[-1]


def validate_prices(
    adjusted: pd.DataFrame,
    close: pd.DataFrame,
    cutoff: pd.Timestamp,
    tickers,
    check_freshness: bool = True,
    requested_start: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    for label, frame in (("adjusted", adjusted), ("close", close)):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise DataUnavailableError(f"No {label} prices downloaded.")
        if frame.columns.has_duplicates:
            raise ValueError(f"Duplicate {label} ETF columns.")
        missing = set(tickers) - set(frame.columns)
        if missing:
            raise DataUnavailableError(f"Missing {label} ETF prices: {', '.join(sorted(missing))}")
        data = frame.loc[:, list(tickers)].copy()
        data.index = pd.to_datetime(data.index, errors="raise").tz_localize(None)
        if data.index.hasnans or not data.index.equals(data.index.normalize()):
            raise ValueError("Invalid daily dates: expected non-null midnight session labels.")
        data = data.loc[data.index < cutoff].sort_index()
        if data.index.has_duplicates:
            raise ValueError("Duplicate market dates in price data.")
        data = data.dropna(how="all")
        if data.empty or data.isna().any().any():
            raise DataUnavailableError(f"Incomplete {label} data; prices will not be filled.")
        values = data.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError(f"Invalid {label} prices.")
        frames.append(data)
    adjusted, close = frames
    if not adjusted.index.equals(close.index):
        raise ValueError("Adjusted and unadjusted price dates do not match.")
    if len(adjusted) < 252 * 5:
        raise ValueError("At least five years of common daily history are required.")
    start = pd.Timestamp(requested_start) if requested_start is not None else adjusted.index[0]
    expected = session_dates(start, adjusted.index[-1])
    unexpected = adjusted.index.difference(expected)
    if len(unexpected):
        raise ValueError(f"Off-calendar or out-of-range date: {unexpected[0].date()}.")
    missing = expected.difference(adjusted.index)
    if len(missing):
        raise DataUnavailableError(
            f"Missing trading sessions (data gap): {len(missing)}, first {missing[0].date()}."
        )
    if check_freshness and adjusted.index[-1] != latest_session(cutoff):
        raise DataUnavailableError(
            f"Stale prices: latest {adjusted.index[-1].date()}, "
            f"expected {latest_session(cutoff).date()}."
        )
    return adjusted, close


def is_transient(exc: Exception) -> bool:
    """Handle both requests and curl_cffi without importing private provider APIs."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is not None:
        return status == 429 or 500 <= status < 600
    return isinstance(exc, (TimeoutError, ConnectionError, OSError, DataUnavailableError)) or (
        type(exc).__name__ in {
            "YFRateLimitError", "Timeout", "ConnectTimeout", "ReadTimeout",
            "ConnectionError", "DNSError", "ChunkedEncodingError", "RemoteDisconnected",
        }
    )


def download_prices(
    cutoff: pd.Timestamp, tickers, attempts: int = MAX_ATTEMPTS,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    import yfinance as yf

    if not 1 <= attempts <= MAX_ATTEMPTS:
        raise ValueError(f"Download attempts must be between 1 and {MAX_ATTEMPTS}.")
    start = cutoff - pd.DateOffset(years=10)
    # Avoid multiplying our attempt budget by provider-level retries.
    previous_retries = yf.config.network.retries
    yf.config.network.retries = 0
    try:
        for attempt in range(1, attempts + 1):
            try:
                raw = yf.download(
                    list(tickers), start=str(start.date()), end=str(cutoff.date()),
                    auto_adjust=False, actions=False, progress=False, threads=False,
                    timeout=30, group_by="column", multi_level_index=True,
                    keepna=True,
                )
                if raw is None or raw.empty:
                    raise DataUnavailableError("Market-data download failed: empty provider response.")
                if not isinstance(raw.columns, pd.MultiIndex) or not {
                    "Adj Close", "Close",
                }.issubset(raw.columns.get_level_values(0)):
                    raise ValueError("Provider schema must include adjusted and unadjusted closes.")
                adjusted, close = validate_prices(
                    raw["Adj Close"], raw["Close"], cutoff, tickers, requested_start=start,
                )
                return adjusted, close, attempt
            except Exception as exc:
                if not is_transient(exc):
                    raise
                if attempt == attempts:
                    raise ValueError(
                        f"Market-data download failed after {attempt} attempt(s): {exc}. "
                        "No cache or synthetic fallback was used."
                    ) from exc
                delay = 2 ** (attempt - 1)
                print(
                    f"Download attempt {attempt}/{attempts} unavailable; retrying in {delay}s.",
                    file=sys.stderr,
                )
                time.sleep(delay)
    finally:
        yf.config.network.retries = previous_retries
    raise RuntimeError("Download attempt loop ended unexpectedly.")
