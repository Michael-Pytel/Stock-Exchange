# =============================================================================
# env/trading_env.py
# =============================================================================
# Reward components:
#   aggressive:   step_return + trend_bonus - churn_penalty
#   conservative: step_return + trend_bonus - churn_penalty - opportunity_cost
#
# opportunity_cost:
#   sitting out on a positive market day  -> penalty  (missed opportunity)
#   sitting out on a negative market day  -> reward   (correctly avoided loss)
# =============================================================================

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import config
from data.processor import FEATURE_COLS, N_FEATURES


class TradingEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        ticker_data  : dict[str, pd.DataFrame],
        mode         : str = "train",
        risk_profile : str = "aggressive",
        render_mode  : str | None = None,
    ):
        super().__init__()

        self.ticker_data  = ticker_data
        self.tickers      = list(ticker_data.keys())
        self.mode         = mode
        self.render_mode  = render_mode
        self.window       = config.WINDOW_SIZE

        # Load risk profile settings
        profile = config.RISK_PROFILES[risk_profile]
        self.stop_loss        = profile["stop_loss"]
        self.min_hold_steps   = profile["min_hold_steps"]
        self.trend_bonus      = profile["trend_bonus"]
        self.churn_penalty    = profile["churn_penalty"]
        self.opportunity_cost = profile["opportunity_cost"]

        # --- Spaces ----------------------------------------------------------
        obs_size = self.window * N_FEATURES + 3
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_size,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)   # 0=Hold, 1=Buy, 2=Sell

        # Initialised in reset()
        self.df            = None
        self.current_step  = 0
        self.balance       = config.INITIAL_BALANCE
        self.shares_held   = 0
        self.net_worth     = config.INITIAL_BALANCE
        self.prev_worth    = config.INITIAL_BALANCE
        self.current_price = 0.0
        self._ticker       = None
        self._buy_step     = None
        self._buy_price    = None

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _select_df(self) -> pd.DataFrame:
        ticker = np.random.choice(self.tickers)
        self._ticker = ticker
        df = self.ticker_data[ticker]

        if self.mode == "train":
            mask = df["date"] <= config.TRAIN_END
        elif self.mode == "val":
            mask = (df["date"] > config.TRAIN_END) & (df["date"] <= config.VAL_END)
        else:
            mask = df["date"] > config.VAL_END

        return df[mask].reset_index(drop=True)

    def _get_obs(self) -> np.ndarray:
        start     = max(0, self.current_step - self.window + 1)
        window_df = self.df.iloc[start : self.current_step + 1][FEATURE_COLS]

        if len(window_df) < self.window:
            pad        = np.zeros((self.window - len(window_df), N_FEATURES), dtype=np.float32)
            window_arr = np.vstack([pad, window_df.values])
        else:
            window_arr = window_df.values.astype(np.float32)

        flat_features  = window_arr.flatten()
        position_flag  = np.float32(1.0 if self.shares_held > 0 else 0.0)
        balance_norm   = np.float32(self.balance / config.INITIAL_BALANCE - 1.0)
        unrealised_pnl = np.float32(
            (self.shares_held * self.current_price) / config.INITIAL_BALANCE
        )
        return np.concatenate([flat_features, [position_flag, balance_norm, unrealised_pnl]])

    def _execute_sell(self):
        trade_value      = self.shares_held * self.current_price
        cost             = trade_value * config.TRANSACTION_COST
        self.balance    += trade_value - cost
        self.shares_held = 0

    def _compute_reward(self, action: int) -> float:
        # Base: normalised daily PnL
        step_return = (self.net_worth - self.prev_worth) / config.INITIAL_BALANCE

        # Trend bonus: amplify reward when holding a winning position
        trend_bonus = 0.0
        if self.shares_held > 0 and step_return > 0:
            trend_bonus = step_return * self.trend_bonus

        # Churn penalty: discourage selling within min_hold_steps of buying
        churn_pen = 0.0
        if action == 2 and self._buy_step is not None:
            steps_held = self.current_step - self._buy_step
            if steps_held < self.min_hold_steps:
                churn_pen = self.churn_penalty * (self.min_hold_steps - steps_held)

        # Opportunity cost: only active in conservative profile (scale > 0)
        # sitting out on up day   -> penalty  (missed the move)
        # sitting out on down day -> reward   (correctly avoided loss)
        opp_cost = 0.0
        if self.shares_held == 0 and self.opportunity_cost > 0:
            market_return = float(self.df.iloc[self.current_step]["return_1d"])
            opp_cost = market_return * self.opportunity_cost

        return float(step_return + trend_bonus - churn_pen - opp_cost)

    # -------------------------------------------------------------------------
    # Gymnasium API
    # -------------------------------------------------------------------------

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        self.df = self._select_df()

        if self.mode == "train":
            max_start         = max(self.window + 1, len(self.df) - self.window - 10)
            self.current_step = np.random.randint(self.window, max_start)
        else:
            self.current_step = self.window

        self.balance       = config.INITIAL_BALANCE
        self.shares_held   = 0
        self.net_worth     = config.INITIAL_BALANCE
        self.prev_worth    = config.INITIAL_BALANCE
        self.current_price = float(self.df.iloc[self.current_step]["close"])
        self._buy_step     = None
        self._buy_price    = None

        return self._get_obs(), {}

    def step(self, action: int):
        self.current_price = float(self.df.iloc[self.current_step]["close"])
        self.prev_worth    = self.net_worth

        # --- Execute action --------------------------------------------------
        if action == 1:   # Buy
            shares_to_buy = min(
                config.MAX_SHARES,
                int(self.balance / (self.current_price * (1 + config.TRANSACTION_COST)))
            )
            if shares_to_buy > 0:
                trade_value       = shares_to_buy * self.current_price
                cost              = trade_value * config.TRANSACTION_COST
                self.balance     -= trade_value + cost
                self.shares_held += shares_to_buy
                self._buy_step    = self.current_step
                self._buy_price   = self.current_price

        elif action == 2:   # Sell
            if self.shares_held > 0:
                self._execute_sell()

        # --- Update portfolio -------------------------------------------------
        self.net_worth = self.balance + self.shares_held * self.current_price

        # --- Reward -----------------------------------------------------------
        reward = self._compute_reward(action)

        # --- Advance ----------------------------------------------------------
        self.current_step += 1
        terminated = self.current_step >= len(self.df) - 1
        truncated  = False

        if self.net_worth < config.INITIAL_BALANCE * 0.2:
            terminated = True
            reward    -= 1.0

        obs  = self._get_obs()
        info = {
            "ticker"      : self._ticker,
            "net_worth"   : self.net_worth,
            "balance"     : self.balance,
            "shares_held" : self.shares_held,
            "step"        : self.current_step,
        }
        return obs, reward, terminated, truncated, info

    def render(self):
        if self.render_mode == "human":
            date = self.df.iloc[self.current_step]["date"]
            print(
                f"[{self._ticker}] {date.date()} | "
                f"Price: ${self.current_price:.2f} | "
                f"Shares: {self.shares_held} | "
                f"Balance: ${self.balance:.2f} | "
                f"Net worth: ${self.net_worth:.2f}"
            )