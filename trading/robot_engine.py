"""
trading/robot_engine.py

Thin Django-side wrapper around the trading_bot package.
Models are loaded once (call load_models() from AppConfig.ready()).
Views import get_signal() and get_backtest() directly.

Set TRADING_BOT_PATH in .env if the bot lives outside the Django project:
    TRADING_BOT_PATH=/absolute/path/to/trading_bot
"""

import os
import sys
import logging

logger = logging.getLogger(__name__)


# ── Path setup ────────────────────────────────────────────────────────────────
def _ensure_bot_on_path():
    from decouple import config as _cfg
    bot_path = _cfg("TRADING_BOT_PATH", default=None)
    if bot_path and bot_path not in sys.path:
        sys.path.insert(0, bot_path)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


# ── Module-level model cache ──────────────────────────────────────────────────
_models = {
    "aggressive":   None,
    "conservative": None,
}
_models_loaded = False


def load_models():
    """Called once from TradingConfig.ready(). Loads both PPO models."""
    global _models_loaded
    _ensure_bot_on_path()

    try:
        from stable_baselines3 import PPO
        from decouple import config as _cfg

        bot_path = _cfg("TRADING_BOT_PATH", default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "trading_bot"
        ))

        for profile in ("aggressive", "conservative"):
            model_path = os.path.join(bot_path, "models", profile, "best_model")
            if os.path.exists(model_path + ".zip"):
                _models[profile] = PPO.load(model_path)
                logger.info("Loaded %s PPO model from %s", profile, model_path)
            else:
                logger.warning(
                    "Model not found: %s.zip — %s profile unavailable",
                    model_path, profile
                )

        _models_loaded = True

    except Exception as exc:
        logger.error("load_models() failed: %s", exc)
        raise


# ── Signal ────────────────────────────────────────────────────────────────────
def get_signal(ticker: str, risk_profile: str = "aggressive") -> dict:
    """
    Returns today's action for a single ticker.

    Returns:
        {
            "action":       "Buy" | "Hold" | "Sell",
            "action_int":   0 | 1 | 2,
            "ticker":       str,
            "risk_profile": str,
            "error":        None | str,
        }
    """
    _ensure_bot_on_path()
    result = {
        "ticker": ticker, "risk_profile": risk_profile,
        "action": "Hold", "action_int": 0, "error": None,
    }

    model = _models.get(risk_profile)
    if model is None:
        result["error"] = f"Model for profile '{risk_profile}' is not loaded."
        return result

    try:
        from trading.trading_bot.data.fetcher    import load_all
        from trading.trading_bot.data.processor  import process_all
        from trading.trading_bot.env.trading_env import TradingEnv

        raw_data  = load_all()
        processed = process_all(raw_data)

        if ticker not in processed:
            result["error"] = f"No data available for {ticker}."
            return result

        env = TradingEnv(
            {ticker: processed[ticker]},
            mode="test",
            risk_profile=risk_profile,
        )
        obs, _ = env.reset()

        # Step through all historical bars so the final obs = today's market state
        done = False
        while not done:
            obs, _, terminated, truncated, _ = env.step(1)  # 1 = Hold, no trades
            done = terminated or truncated

        action_int, _ = model.predict(obs, deterministic=True)
        action_int = int(action_int)

        result["action"]     = ["Hold", "Buy", "Sell"][action_int]
        result["action_int"] = action_int

    except Exception as exc:
        logger.error("get_signal(%s, %s) failed: %s", ticker, risk_profile, exc)
        result["error"] = str(exc)

    return result


# ── Win rate helper ───────────────────────────────────────────────────────────
def _compute_win_rate(log) -> float:
    """
    Pair each Buy with the next Sell (or end of episode if still holding).
    Returns percentage of those trades that were profitable.
    """
    buy_price = None
    wins  = 0
    total = 0

    for _, row in log.iterrows():
        action = row["action"]
        close  = row["close"]

        if action == "Buy" and buy_price is None:
            buy_price = close

        elif action == "Sell" and buy_price is not None:
            total += 1
            if close > buy_price:
                wins += 1
            buy_price = None

    # Still holding at end of episode — count as a trade using final close
    if buy_price is not None:
        total += 1
        final_close = log["close"].iloc[-1]
        if final_close > buy_price:
            wins += 1

    if total == 0:
        return 0.0
    return round(wins / total * 100, 1)


# ── Backtest ──────────────────────────────────────────────────────────────────
def get_backtest(ticker: str, risk_profile: str = "aggressive") -> dict:
    """
    Runs a full backtest episode for the given ticker + risk profile.

    Matches actual backtest.py signatures:
        run_episode(model, env)       → pd.DataFrame
        compute_metrics(log, ticker)  → dict  (keys like "Agent Ret %")
        buy_and_hold(log)             → pd.Series

    Returns JSON-serialisable dict for the robot API view.
    """
    _ensure_bot_on_path()
    result = {
        "ticker": ticker, "risk_profile": risk_profile,
        "metrics": {}, "equity_curve": [], "bah_curve": [],
        "dates": [], "trade_log": [], "error": None,
    }

    model = _models.get(risk_profile)
    if model is None:
        result["error"] = f"Model for profile '{risk_profile}' is not loaded."
        return result

    try:
        from trading.trading_bot.data.fetcher    import load_all
        from trading.trading_bot.data.processor  import process_all
        from trading.trading_bot.env.trading_env import TradingEnv
        from trading.trading_bot.backtest        import run_episode, compute_metrics, buy_and_hold

        raw_data  = load_all()
        processed = process_all(raw_data)

        if ticker not in processed:
            result["error"] = f"No data available for {ticker}."
            return result

        env = TradingEnv(
            {ticker: processed[ticker]},
            mode="test",
            risk_profile=risk_profile,
        )

        # backtest.py: run_episode(model, env)  <- model is first argument
        log     = run_episode(model, env)
        metrics = compute_metrics(log, ticker)
        bah     = buy_and_hold(log)

        win_rate_pct = _compute_win_rate(log)

        result["metrics"] = {
            "total_return_pct":     metrics["Agent Ret %"],
            "bah_return_pct":       metrics["BnH Ret %"],
            "outperform_pct":       metrics["Outperform %"],
            "sharpe":               metrics["Agent Sharpe"],
            "bah_sharpe":           metrics["BnH Sharpe"],
            "max_drawdown_pct":     metrics["Agent MaxDD %"],
            "bah_max_drawdown_pct": metrics["BnH MaxDD %"],
            "trades":               int(metrics["Trades"]),
            "agent_final":          float(metrics["Agent Final $"]),
            "bah_final":            float(metrics["BnH Final $"]),
            "win_rate_pct":         win_rate_pct,
        }
        result["equity_curve"] = [round(float(v), 2) for v in log["net_worth"].tolist()]
        result["bah_curve"]    = [round(float(v), 2) for v in bah.tolist()]
        result["dates"]        = [str(d)[:10]         for d in log["date"].tolist()]

        # Full trade log — pair each Buy with the next Sell into round-trips
        action_col = "action"   if "action"   in log.columns else None
        worth_col  = "net_worth"

        round_trips = []
        open_trade  = None

        for _, row in log.iterrows():
            act   = str(row[action_col]) if action_col else "Hold"
            price = float(row["close"])
            date  = str(row["date"])[:10]
            worth = float(row[worth_col])

            if act == "Buy" and open_trade is None:
                open_trade = {
                    "buy_date":  date,
                    "buy_price": price,
                    "worth_at_buy": worth,
                }

            elif act == "Sell" and open_trade is not None:
                buy_price  = open_trade["buy_price"]
                # shares = how much of the portfolio was deployed / buy price
                # approximate from net_worth change at buy vs sell
                shares_approx = round(
                    (open_trade["worth_at_buy"] * 0.95) / buy_price, 4
                ) if buy_price > 0 else 0
                pnl = round((price - buy_price) * shares_approx, 2)

                round_trips.append({
                    "buy_date":   open_trade["buy_date"],
                    "sell_date":  date,
                    "buy_price":  round(buy_price, 2),
                    "sell_price": round(price, 2),
                    "shares":     shares_approx,
                    "pnl":        pnl,
                    "net_worth":  round(worth, 2),
                })
                open_trade = None

        # Still holding at episode end — show as open position
        if open_trade is not None:
            final_row   = log.iloc[-1]
            final_price = float(final_row["close"])
            buy_price   = open_trade["buy_price"]
            shares_approx = round(
                (open_trade["worth_at_buy"] * 0.95) / buy_price, 4
            ) if buy_price > 0 else 0
            pnl = round((final_price - buy_price) * shares_approx, 2)
            round_trips.append({
                "buy_date":   open_trade["buy_date"],
                "sell_date":  "Open",
                "buy_price":  round(buy_price, 2),
                "sell_price": round(final_price, 2),
                "shares":     shares_approx,
                "pnl":        pnl,
                "net_worth":  round(float(log.iloc[-1][worth_col]), 2),
            })

        result["trade_log"] = round_trips

    except Exception as exc:
        logger.error("get_backtest(%s, %s) failed: %s", ticker, risk_profile, exc)
        result["error"] = str(exc)

    return result