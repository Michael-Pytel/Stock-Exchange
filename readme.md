# AI Trading Platform

An algorithmic trading platform combining reinforcement learning, probabilistic time-series forecasting, and paper trading with real-time market data. The platform is built around three core modules: a PPO-based trading robot, an AutoGluon ensemble forecaster, and a full paper trading interface — all powered by live data from Alpaca Markets.

---

## Trading Robot (PPO)

The robot is trained using the Proximal Policy Optimization algorithm (Stable-Baselines3) and makes Buy / Hold / Sell decisions based on the current market state. It operates on two risk profiles that reflect different trading personalities:

- **Aggressive** — larger position sizes, higher trading frequency, higher potential returns but also higher volatility and drawdown
- **Conservative** — smaller positions, fewer entries, prioritises capital preservation and lower drawdown over maximising returns

### Today's Signal

After selecting a ticker and a risk profile, the robot replays the full historical market data to reconstruct the current market state, then issues a single signal for today: **BUY**, **HOLD**, or **SELL**. The signal is displayed as a prominent badge alongside the active risk profile label.

### Backtest

Beyond the daily signal, the robot page runs a full backtest episode — the agent steps through the entire historical dataset and trades autonomously. The results are presented in two ways:

**Equity curve chart** — an interactive line chart showing the agent's portfolio value (starting from $10,000) plotted against a passive Buy & Hold strategy over the same period. The agent's line is colour-coded green when it finishes above B&H and red when it underperforms. Both series share a crosshair tooltip showing the exact dollar value on any given date.

**Performance metrics panel** — a set of key statistics shown side by side with their B&H equivalents:

| Metric | Description |
|---|---|
| Total Return % | Cumulative return of the agent over the full episode |
| B&H Return % | Return of a passive buy-and-hold strategy over the same period |
| Outperform % | Agent's return minus B&H return — how much alpha was generated |
| Sharpe Ratio | Risk-adjusted return (agent vs B&H) |
| Max Drawdown % | Largest peak-to-trough decline during the episode |
| Win Rate % | Percentage of closed round-trip trades that were profitable |
| Trades | Total number of completed Buy→Sell round-trips |

**Trade log table** — a full breakdown of every round-trip trade in the backtest, with columns for buy date, sell date, number of shares, buy price, sell price, P&L per trade, and portfolio net worth at the time of the sell. Open positions (bought but not yet sold by the end of the episode) are flagged with an "Open" badge and show the current price as the reference exit.

### Deploying the Robot

On the robot page the user can deploy the agent to trade live on their paper account. Before deploying, the user sets a budget (minimum $100) — the portion of the virtual balance allocated to this robot session. Once deployed, a green status dot appears alongside the active profile and budget. The robot can be stopped at any time, which closes the session and returns control to the user. Each ticker has its own independent session, so multiple robots can run simultaneously on different stocks.

A live trade history tab shows every real order the robot has placed on the user's paper account, with timestamps, action type, execution price, shares, remaining balance, and notes.

---

## Forecasting (AutoGluon TimeSeries)

The forecasting module predicts the next 5 daily returns for a selected ticker using a trained AutoGluon ensemble. The model is not a point forecast — it produces a full probability distribution at each future step, represented by seven quantiles: 0.05, 0.10, 0.30, 0.50 (median), 0.70, 0.90, 0.95.

### Ensemble Composition

The final model used for predictions is WeightedEnsemble. The ensemble weights are determined automatically by AutoGluon during validation:

| Model | Type | Weight |
|---|---|---|
| RecursiveTabular | Gradient Boosting | 44.8% |
| Temporal Fusion Transformer | Transformer | 27.6% |
| DeepAR | Probabilistic RNN | 24.1% |
| PatchTST | Transformer | 3.4% |

### Forecast Chart

The forecast chart shows 40 days of historical log-returns (grey line) followed by the 5-day probabilistic forecast, connected smoothly at the last known value. The chart renders:

- **Median line** — the model's central prediction for each of the next 5 days
- **Inner band (Q 10–90%)** — the range the model expects the return to fall within with 80% probability
- **Outer band (Q 5–95%)** — the wider 90% confidence interval
- **Return threshold line** — a user-defined stop-loss level drawn as a dashed red horizontal line across the entire chart

Hovering over the forecast region shows a tooltip with all five quantile values for that day.

### Return Risk Analysis

The user sets a return threshold (stop-loss level) before requesting the forecast. The system compares this level against the predicted distribution for each of the 5 forecast days and classifies the risk of the stop being triggered:

| Risk Level | Condition |
|---|---|
| **Very Low Risk** | Stop is below Q(0.05) — less than 5% probability of being hit |
| **Low Risk** | Stop falls between Q(0.05) and Q(0.10) |
| **Monitor** | Stop falls between Q(0.10) and Q(0.30) |
| **High Risk** | Stop is above Q(0.30) — more than 30% probability of being hit |

The results are displayed in a per-day risk table showing Q(0.05), Q(0.10), Q(0.30), the median, the quantile range the stop falls in, and the final risk label with colour coding.

### Model Quality Metrics

The ML models page shows a full evaluation of the forecaster per ticker:

| Metric | Description |
|---|---|
| MASE | Mean Absolute Scaled Error — forecast error relative to a naïve baseline (lower is better) |
| RMSE | Root Mean Squared Error on the test set |
| WQL | Weighted Quantile Loss — evaluates the accuracy of the entire predicted distribution, not just the median |
| Hit Ratio | Fraction of days where the actual direction of the return was the same as predicted (profit/loss) (higher is better; >50% beats random) |
| Winkler Score | Penalises both overly wide and overly narrow confidence intervals |
| Coverage | Empirical check that predicted intervals (α = 0.05 / 0.10 / 0.30 / 0.90) have the correct real-world coverage |

---

## Paper Trading

Each user receives a virtual dollar balance and can trade all 9 supported stocks without risking real capital. All prices come from Alpaca Markets and reflect real market data.

### Stock Chart

The trading page is built around a professional-grade interactive chart with the following options:

**Chart types** — the user can switch between four display modes:
- **Line** — a simple closing price line, colour-coded green or red based on the period's direction
- **Candlestick** — full OHLC candles with green/red colouring
- **Mountain** — a filled area chart below the closing price line
- **Baseline** — a dual-coloured chart that splits above and below a user-defined baseline price; the baseline can be dragged up and down directly on the chart

**Timeframes** — 1D (5-minute bars), 1W (hourly), 1M, 3M, YTD, 1Y, 5Y, and ALL. Scrolling to the left edge of the chart automatically loads older data. For the 5Y and ALL timeframes, the data is served from pre-downloaded Parquet files to work around Alpaca's IEX history limit.

**Technical indicators** — overlaid on the main chart:
- SMA 20 and SMA 50 (simple moving averages)
- EMA 20 (exponential moving average)
- Bollinger Bands (20-period, ±2σ)

**RSI panel** — a separate sub-chart below the volume bars showing the 14-period Relative Strength Index with overbought (70) and oversold (30) reference lines.

**Volume bars** — synchronised with the main chart (scroll and zoom are locked together), colour-coded teal for up-days and red for down-days.

A **market status indicator** in the header shows whether the US market is currently Pre-Market, Open, After-Hours, or Closed, updating every minute based on Eastern Time.

### Order Panel

The order panel on the right side of the trading page lets the user place simulated Buy and Sell orders:

- **Buy** — enter the number of shares or a dollar amount; the estimated total is shown before confirmation; the order is validated against the user's current virtual balance
- **Sell** — only available when the user holds a position in that stock; shows the current number of shares held, average buy price, unrealised P&L, and percentage return on the position

After executing an order, the balance, position size, and unrealised P&L update immediately on the page.

A **risk disclaimer** is shown to first-time users before any order can be placed, requiring explicit acceptance.

---

## Feature Engineering

Raw OHLCV data is enriched with over 50 derived features before training and inference:

- Fractional returns and log-returns (1, 2, 3, 5, 30 days)
- Volume percentage change and log-volume (1, 2, 5, 30 days)
- Simple moving averages — SMA 2, 5, 8, 30
- Historical volatility and EWMA volatility (span=10); Z-score of 5-day volatility against a 20-day rolling window
- 20-day rolling skewness and kurtosis of log-returns (fat tail and asymmetry signals)
- RSI (14-period) and RSI weighted by price direction
- Lagged closing prices (1, 2, 3, 5, 10, 30 days)
- Intrabar candle position: `(close − low) / (high − low)`
- Price direction, trend strength, and direction-change flags over 1, 3, 5, 10, and 20 days

---

## Supported Tickers

AAPL · AMZN · GOOGL · JPM · META · MSFT · NVDA · TSLA · V

### Authors 
* [Michał Pytel](https://github.com/Michael-Pytel)
* [Katarzyna Rogalska](https://github.com/katarzynarogalska) 
