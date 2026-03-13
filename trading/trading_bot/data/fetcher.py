# =============================================================================
# data/fetcher.py — Fetch historical daily bars from Alpaca, save as parquet
# =============================================================================

import os
import time
import pandas as pd
from datetime import datetime
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests   import StockBarsRequest
from alpaca.data.timeframe  import TimeFrame

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import config

# ── Resolve DATA_DIR to an absolute path relative to this file ────────────────
# This ensures parquet files are always found regardless of where Django's
# working directory is when load_all() is called.
_BOT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BOT_DIR, os.path.basename(config.DATA_DIR))


def fetch_ticker(client: StockHistoricalDataClient, ticker: str) -> pd.DataFrame:
    """Fetch daily OHLCV bars for a single ticker from Alpaca."""
    request = StockBarsRequest(
        symbol_or_symbols = ticker,
        timeframe          = TimeFrame.Day,
        start              = datetime.strptime(config.DATA_START, "%Y-%m-%d"),
        end                = datetime.strptime(config.DATA_END,   "%Y-%m-%d"),
        adjustment         = "all",
    )
    bars = client.get_stock_bars(request)
    df   = bars.df

    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index(level=0, drop=True)
    df.index.name = "date"
    df = df.reset_index()

    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.sort_values("date").reset_index(drop=True)

    print(f"  {ticker}: {len(df)} rows  "
          f"({df['date'].min().date()} → {df['date'].max().date()})")
    return df


def fetch_all(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """
    Fetch all tickers defined in config.TICKERS.
    Caches each ticker as a parquet file in DATA_DIR.
    """
    os.makedirs(_DATA_DIR, exist_ok=True)

    client = StockHistoricalDataClient(
        api_key    = config.ALPACA_API_KEY,
        secret_key = config.ALPACA_SECRET_KEY,
    )

    data = {}
    for ticker in config.TICKERS:
        path = os.path.join(_DATA_DIR, f"{ticker}.parquet")

        if os.path.exists(path) and not force_refresh:
            print(f"  {ticker}: loading from cache ({path})")
            data[ticker] = pd.read_parquet(path)
            continue

        print(f"  {ticker}: fetching from Alpaca …")
        try:
            df = fetch_ticker(client, ticker)
            df.to_parquet(path, index=False)
            data[ticker] = df
            time.sleep(0.3)
        except Exception as e:
            print(f"  ERROR fetching {ticker}: {e}")

    return data


def load_all() -> dict[str, pd.DataFrame]:
    """Load all cached parquet files (assumes fetch_all() has been run before)."""
    data = {}
    for ticker in config.TICKERS:
        path = os.path.join(_DATA_DIR, f"{ticker}.parquet")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"No cached data for {ticker}. "
                f"Expected at: {path}\n"
                f"Run fetch_all() first."
            )
        data[ticker] = pd.read_parquet(path)
    return data


def refresh_tickers(tickers: list = None) -> dict:
    """
    Incrementally update parquet files — only fetch days missing since
    the last cached date.  Much faster than fetch_all(force_refresh=True).
 
    Parameters
    ----------
    tickers : list, optional
        Subset of tickers to refresh. Defaults to config.TICKERS.
 
    Returns
    -------
    dict[ticker -> DataFrame]  (full updated dataframes)
    """
    from datetime import datetime, timedelta, date
 
    if tickers is None:
        tickers = config.TICKERS
 
    os.makedirs(_DATA_DIR, exist_ok=True)
 
    client = StockHistoricalDataClient(
        api_key    = config.ALPACA_API_KEY,
        secret_key = config.ALPACA_SECRET_KEY,
    )
 
    data = {}
    today = date.today()
 
    for ticker in tickers:
        path = os.path.join(_DATA_DIR, f"{ticker}.parquet")
 
        if not os.path.exists(path):
            # No cache at all — do a full fetch
            print(f"  {ticker}: no cache, fetching full history …")
            try:
                df = fetch_ticker(client, ticker)
                df.to_parquet(path, index=False)
                data[ticker] = df
            except Exception as e:
                print(f"  ERROR fetching {ticker}: {e}")
            time.sleep(0.3)
            continue
 
        # Load existing cache and find last date
        existing = pd.read_parquet(path)
        last_date = pd.to_datetime(existing["date"]).max().date()
 
        # Already up to date (last trading day)
        if last_date >= today - timedelta(days=1):
            print(f"  {ticker}: already up to date ({last_date})")
            data[ticker] = existing
            continue
 
        # Fetch only the missing window
        fetch_start = last_date + timedelta(days=1)
        print(f"  {ticker}: fetching {fetch_start} → {today} …")
 
        try:
            request = StockBarsRequest(
                symbol_or_symbols = ticker,
                timeframe          = TimeFrame.Day,
                start              = datetime.combine(fetch_start, datetime.min.time()),
                end                = datetime.combine(today,       datetime.min.time()),
                adjustment         = "all",
            )
            bars = client.get_stock_bars(request)
            new_df = bars.df
 
            if new_df.empty:
                print(f"  {ticker}: no new bars")
                data[ticker] = existing
                continue
 
            if isinstance(new_df.index, pd.MultiIndex):
                new_df = new_df.reset_index(level=0, drop=True)
            new_df.index.name = "date"
            new_df = new_df.reset_index()
            new_df = new_df[["date", "open", "high", "low", "close", "volume"]].copy()
            new_df["date"] = pd.to_datetime(new_df["date"]).dt.tz_localize(None)
 
            # Append and deduplicate
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
            combined.to_parquet(path, index=False)
            data[ticker] = combined
            print(f"  {ticker}: added {len(new_df)} new rows "
                  f"(total {len(combined)})")
 
        except Exception as e:
            print(f"  ERROR refreshing {ticker}: {e}")
            data[ticker] = existing
 
        time.sleep(0.3)
 
    return data

if __name__ == "__main__":
    print("Fetching market data …")
    data = fetch_all(force_refresh=False)
    print(f"\nDone. {len(data)} tickers loaded.")

