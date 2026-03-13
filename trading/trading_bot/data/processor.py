# =============================================================================
# data/processor.py — Add technical indicators and build scale-invariant features
# =============================================================================
# All features are SCALE-INVARIANT so the same model works across all tickers
# regardless of absolute price level (SPY ~$500 vs NVDA ~$800, etc.)
# =============================================================================

import numpy as np
import pandas as pd
import ta
import ta.momentum
import ta.trend
import ta.volatility
import ta.volume

import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import config


# Features that will form the observation space (must match env/trading_env.py)
FEATURE_COLS = [
    "return_1d",       # 1-day return
    "return_5d",       # 5-day return
    "return_20d",      # 20-day return (monthly momentum)
    "rsi_14",          # RSI [0, 100] → normalised to [-1, 1]
    "macd_norm",       # MACD line / close price  (scale-free)
    "bb_pct",          # Bollinger %B  [0, 1]
    "atr_norm",        # ATR / close  (volatility as fraction of price)
    "volume_norm",     # z-score of log-volume over 20-day rolling window
    "ema_ratio_9_21",  # EMA(9) / EMA(21) − 1  (trend signal)
    "ema_ratio_21_50", # EMA(21) / EMA(50) − 1  (longer trend)
]

N_FEATURES = len(FEATURE_COLS)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators and return scale-invariant features."""
    df = df.copy().sort_values("date").reset_index(drop=True)

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # --- Price returns -------------------------------------------------------
    df["return_1d"]  = close.pct_change(1)
    df["return_5d"]  = close.pct_change(5)
    df["return_20d"] = close.pct_change(20)

    # --- RSI → normalised to [-1, 1] -----------------------------------------
    rsi = ta.momentum.RSIIndicator(close=close, window=14).rsi()
    df["rsi_14"] = (rsi - 50.0) / 50.0

    # --- MACD / close price --------------------------------------------------
    macd_ind = ta.trend.MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
    df["macd_norm"] = macd_ind.macd() / close

    # --- Bollinger %B --------------------------------------------------------
    bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    upper = bb.bollinger_hband()
    lower = bb.bollinger_lband()
    df["bb_pct"] = (close - lower) / (upper - lower + 1e-9)

    # --- ATR / close (normalised volatility) ---------------------------------
    atr = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
    df["atr_norm"] = atr / close

    # --- Volume: z-score of log-volume ---------------------------------------
    log_vol      = np.log1p(volume)
    rolling_mean = log_vol.rolling(20).mean()
    rolling_std  = log_vol.rolling(20).std()
    df["volume_norm"] = (log_vol - rolling_mean) / (rolling_std + 1e-9)

    # --- EMA ratios (trend) --------------------------------------------------
    ema9  = ta.trend.EMAIndicator(close=close, window=9).ema_indicator()
    ema21 = ta.trend.EMAIndicator(close=close, window=21).ema_indicator()
    ema50 = ta.trend.EMAIndicator(close=close, window=50).ema_indicator()
    df["ema_ratio_9_21"]  = ema9  / ema21  - 1.0
    df["ema_ratio_21_50"] = ema21 / ema50  - 1.0

    # --- Drop rows with NaN (indicators need warmup period) ------------------
    df = df.dropna(subset=FEATURE_COLS).reset_index(drop=True)

    return df


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split a processed DataFrame into train / val / test sets."""
    train = df[df["date"] <= config.TRAIN_END].reset_index(drop=True)
    val   = df[(df["date"] > config.TRAIN_END) &
               (df["date"] <= config.VAL_END)].reset_index(drop=True)
    test  = df[df["date"]  > config.VAL_END].reset_index(drop=True)
    return train, val, test


def process_all(raw_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Run add_indicators() on every ticker and return processed dict."""
    processed = {}
    for ticker, df in raw_data.items():
        processed[ticker] = add_indicators(df)
        print(f"  {ticker}: {len(processed[ticker])} rows after indicator warmup")
    return processed