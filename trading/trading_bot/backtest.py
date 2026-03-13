# =============================================================================
# backtest.py — Evaluate the trained PPO agent on unseen data
# =============================================================================

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor

import config
from data.fetcher    import load_all
from data.processor  import process_all, split
from env.trading_env import TradingEnv


# ---------------------------------------------------------------------------
# Core evaluation loop
# ---------------------------------------------------------------------------

def run_episode(model, env: TradingEnv) -> pd.DataFrame:
    """Run one full deterministic episode and return a trade log."""
    obs, _ = env.reset()
    done   = False
    rows   = []

    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(int(action))
        done = terminated or truncated

        rows.append({
            "date"        : env.df.iloc[env.current_step - 1]["date"],
            "close"       : env.current_price,
            "action"      : ["Hold", "Buy", "Sell"][int(action)],
            "shares_held" : info["shares_held"],
            "balance"     : info["balance"],
            "net_worth"   : info["net_worth"],
            "reward"      : reward,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Buy-and-hold benchmark
# ---------------------------------------------------------------------------

def buy_and_hold(log: pd.DataFrame) -> pd.Series:
    """Simple buy-and-hold equity curve for comparison."""
    shares = config.INITIAL_BALANCE / log["close"].iloc[0]
    return (shares * log["close"]).rename("Buy & Hold")


# ---------------------------------------------------------------------------
# Metrics — agent + buy & hold side by side
# ---------------------------------------------------------------------------

def compute_metrics(log: pd.DataFrame, ticker: str) -> dict:
    """Compute key performance metrics for both the agent and buy & hold."""
    initial  = config.INITIAL_BALANCE
    final    = log["net_worth"].iloc[-1]
    returns  = log["net_worth"].pct_change().dropna()
    n_days   = len(log)

    # --- Agent ---------------------------------------------------------------
    total_return = (final - initial) / initial * 100
    ann_return   = ((final / initial) ** (252 / n_days) - 1) * 100
    sharpe       = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(252)
    roll_max     = log["net_worth"].cummax()
    max_drawdown = ((log["net_worth"] - roll_max) / roll_max).min() * 100
    n_trades     = (log["action"] != "Hold").sum()

    # --- Buy & Hold ----------------------------------------------------------
    bah          = buy_and_hold(log)
    bah_final    = bah.iloc[-1]
    bah_return   = (bah_final - initial) / initial * 100
    bah_returns  = bah.pct_change().dropna()
    bah_ann      = ((bah_final / initial) ** (252 / n_days) - 1) * 100
    bah_sharpe   = (bah_returns.mean() / (bah_returns.std() + 1e-9)) * np.sqrt(252)
    bah_roll_max = bah.cummax()
    bah_maxdd    = ((bah - bah_roll_max) / bah_roll_max).min() * 100

    return {
        "Ticker"        : ticker,
        "Agent Ret %"   : round(total_return, 2),
        "BnH Ret %"     : round(bah_return, 2),
        "Outperform %"  : round(total_return - bah_return, 2),
        "Agent Sharpe"  : round(sharpe, 2),
        "BnH Sharpe"    : round(bah_sharpe, 2),
        "Agent MaxDD %" : round(max_drawdown, 2),
        "BnH MaxDD %"   : round(bah_maxdd, 2),
        "Trades"        : int(n_trades),
        "Agent Final $" : round(final, 2),
        "BnH Final $"   : round(bah_final, 2),
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_results(logs: dict, save_path: str = "backtest_results.png"):
    n     = len(logs)
    ncols = 3
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(18, nrows * 4))
    axes  = axes.flatten()
    fig.patch.set_facecolor("#0f0f0f")

    for idx, (ticker, log) in enumerate(logs.items()):
        ax  = axes[idx]
        bah = buy_and_hold(log)

        agent_ret  = (log["net_worth"].iloc[-1] / config.INITIAL_BALANCE - 1) * 100
        bah_ret    = (bah.iloc[-1] / config.INITIAL_BALANCE - 1) * 100
        outperform = agent_ret - bah_ret
        color      = "#00ff88" if outperform >= 0 else "#ff4444"

        ax.plot(log["date"], log["net_worth"], color=color,     linewidth=1.5,
                label=f"PPO Agent ({agent_ret:+.1f}%)")
        ax.plot(log["date"], bah,              color="#888888", linewidth=1.0,
                linestyle="--", label=f"Buy & Hold ({bah_ret:+.1f}%)")
        ax.fill_between(log["date"], config.INITIAL_BALANCE, log["net_worth"],
                        where=log["net_worth"] >= config.INITIAL_BALANCE,
                        alpha=0.15, color="#00ff88")
        ax.fill_between(log["date"], config.INITIAL_BALANCE, log["net_worth"],
                        where=log["net_worth"] <  config.INITIAL_BALANCE,
                        alpha=0.15, color="#ff4444")

        out_str = f"{'BEATS' if outperform >= 0 else 'LAGS'} B&H by {abs(outperform):.1f}%"
        ax.set_title(f"{ticker}  |  {out_str}", color="white", fontsize=11, fontweight="bold")
        ax.set_facecolor("#1a1a1a")
        ax.tick_params(colors="grey")
        ax.spines[:].set_color("#333333")
        ax.legend(fontsize=8, facecolor="#1a1a1a", labelcolor="white")

    for j in range(idx + 1, len(axes)):
        axes[j].set_visible(False)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="#0f0f0f")
    print(f"  Chart saved -> {save_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def backtest(model_path: str = "models/aggressive/best_model", split: str = "test", risk_profile: str = "aggressive"):
    print("=" * 60)
    print(f"Backtesting: {model_path}")
    print(f"Profile: {risk_profile.upper()}  |  Split: {split}")
    print("=" * 60)

    raw_data  = load_all()
    processed = process_all(raw_data)

    model = PPO.load(model_path)
    print(f"Model loaded: {model_path}\n")

    all_logs    = {}
    all_metrics = []

    for ticker, df in processed.items():
        env     = TradingEnv({ticker: df}, mode=split, risk_profile=risk_profile)
        log     = run_episode(model, env)
        metrics = compute_metrics(log, ticker)
        all_logs[ticker] = log
        all_metrics.append(metrics)

        beat = "BEAT" if metrics["Outperform %"] >= 0 else "LAG"
        print(
            f"  {ticker:5s}  Agent {metrics['Agent Ret %']:+6.1f}%  "
            f"B&H {metrics['BnH Ret %']:+6.1f}%  "
            f"{beat} {abs(metrics['Outperform %']):.1f}%  "
            f"Sharpe {metrics['Agent Sharpe']:.2f}  "
            f"Trades {metrics['Trades']}"
        )

    summary = pd.DataFrame(all_metrics).set_index("Ticker")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(summary.to_string())

    beats = (summary["Outperform %"] > 0).sum()
    print(f"\nBeats B&H      : {beats}/{len(summary)} tickers")
    print(f"Avg Agent Ret  : {summary['Agent Ret %'].mean():+.2f}%")
    print(f"Avg B&H Ret    : {summary['BnH Ret %'].mean():+.2f}%")
    print(f"Avg Outperform : {summary['Outperform %'].mean():+.2f}%")
    print(f"Avg Sharpe     : {summary['Agent Sharpe'].mean():.2f}")
    print(f"Avg MaxDD      : {summary['Agent MaxDD %'].mean():.2f}%")

    summary.to_csv("backtest_summary.csv")
    print("\nSummary saved -> backtest_summary.csv")

    plot_results(all_logs)

    return summary, all_logs


if __name__ == "__main__":
    backtest(model_path="models/best_model", split="test")