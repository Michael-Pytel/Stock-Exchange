# =============================================================================
# config.py — Central configuration for the trading bot
# =============================================================================

# --- Alpaca API Credentials --------------------------------------------------
import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# --- Universe ----------------------------------------------------------------
TICKERS = ["AAPL", "AMZN", "GOOGL", "JPM", "META", "MSFT", "NVDA", "TSLA", "V"]

# --- Data dates --------------------------------------------------------------
DATA_START = "2016-01-01"
DATA_END   = "2026-03-12"

TRAIN_END  = "2022-12-31"
VAL_END    = "2024-06-30"
# Test set: 2024-07-01 → 2026-03-12

# --- Storage -----------------------------------------------------------------
DATA_DIR = "market_data"

# --- Environment (shared) ----------------------------------------------------
INITIAL_BALANCE  = 10_000.0
TRANSACTION_COST = 0.001
WINDOW_SIZE      = 20
MAX_SHARES       = 10

# --- Risk Profiles -----------------------------------------------------------
#
# Two model variants:
#   aggressive   — no stop loss, rides trends, higher returns, higher drawdown
#   conservative — hard stop loss, cuts losses early, lower drawdown
#
RISK_PROFILES = {
    "aggressive": {
        "stop_loss"         : None,  # no stop loss
        "min_hold_steps"    : 5,
        "trend_bonus"       : 0.5,
        "churn_penalty"     : 0.002,
        "opportunity_cost"  : 0.0,   # no opportunity cost signal
        "model_dir"         : "models/aggressive",
    },
    "conservative": {
        "stop_loss"         : None,  # no hard stop loss — opportunity cost handles exits
        "min_hold_steps"    : 3,
        "trend_bonus"       : 0.3,
        "churn_penalty"     : 0.001,
        "opportunity_cost"  : 0.15,  # stronger signal — rewards sitting out on bad days
        "model_dir"         : "models/conservative",
    },
}

# --- PPO Hyperparameters -----------------------------------------------------
PPO_PARAMS = {
    "learning_rate" : 3e-4,
    "n_steps"       : 2048,
    "batch_size"    : 64,
    "n_epochs"      : 10,
    "gamma"         : 0.99,
    "gae_lambda"    : 0.95,
    "clip_range"    : 0.2,
    "ent_coef"      : 0.01,
    "verbose"       : 1,
}

TOTAL_TIMESTEPS = 3_000_000