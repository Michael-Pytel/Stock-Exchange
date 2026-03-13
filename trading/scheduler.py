"""
trading/scheduler.py

APScheduler-based daily robot execution.
Started once from TradingConfig.ready() in apps.py.

Flow (runs every day at market close ~16:05 ET):
  1. Refresh parquet data for all active tickers (incremental Alpaca fetch)
  2. For each active RobotSession:
       - Run PPO model → get signal (Buy / Hold / Sell)
       - Execute trade against user's demo_balance + Position (same logic as views)
       - Save RobotTrade record
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

_scheduler = None


# ── Start / stop ──────────────────────────────────────────────────────────────
def start():
    global _scheduler
    if _scheduler is not None:
        return  # already running

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron         import CronTrigger
        import django

        _scheduler = BackgroundScheduler(timezone="America/New_York")

        # Run Mon–Fri at 16:05 ET (after US market close)
        _scheduler.add_job(
            run_all_robots,
            trigger  = CronTrigger(
                day_of_week = "mon-fri",
                hour        = 16,
                minute      = 5,
                timezone    = "America/New_York",
            ),
            id             = "daily_robot_run",
            replace_existing = True,
            misfire_grace_time = 3600,  # tolerate up to 1h delay (e.g. server restart)
        )

        _scheduler.start()
        logger.info("Robot scheduler started — daily job at 16:05 ET (Mon–Fri)")

    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc)


def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Robot scheduler stopped")


# ── Main daily job ────────────────────────────────────────────────────────────
def run_all_robots():
    """
    Called by APScheduler every weekday at 16:05 ET.
    Can also be triggered manually from a management command for testing.
    """
    import django
    # Ensure Django apps are ready (needed when called from scheduler thread)
    if not django.apps.apps.ready:
        django.setup()

    from trading.models import RobotSession

    sessions = RobotSession.objects.filter(is_active=True).select_related("user")
    if not sessions.exists():
        logger.info("No active robot sessions — skipping daily run")
        return

    # Collect unique tickers to refresh data once per ticker
    active_tickers = list(sessions.values_list("symbol", flat=True).distinct())
    logger.info("Daily robot run — %d sessions, tickers: %s",
                sessions.count(), active_tickers)

    # 1. Refresh market data for all active tickers
    _refresh_data(active_tickers)

    # 2. Run each session
    for session in sessions:
        try:
            _run_session(session)
        except Exception as exc:
            logger.error("Error running session %s: %s", session, exc)


# ── Incremental data refresh ──────────────────────────────────────────────────
def _refresh_data(tickers: list):
    """Fetch only the missing days from Alpaca and append to parquet."""
    try:
        from trading.robot_engine import _ensure_bot_on_path
        _ensure_bot_on_path()
        from trading.trading_bot.data.fetcher import refresh_tickers
        refresh_tickers(tickers)
    except ImportError:
        # refresh_tickers not available — fall back to full load (no-op if cached)
        logger.warning("refresh_tickers() not found in fetcher — skipping data refresh")
    except Exception as exc:
        logger.error("Data refresh failed: %s", exc)


# ── Execute one session ───────────────────────────────────────────────────────
def _run_session(session):
    """Get signal and execute trade for one RobotSession."""
    from trading.robot_engine import _ensure_bot_on_path, _models
    from trading.models       import RobotTrade, Position
    from django.utils         import timezone

    _ensure_bot_on_path()

    ticker       = session.symbol
    risk_profile = session.risk_profile
    user         = session.user

    model = _models.get(risk_profile)
    if model is None:
        logger.warning("Model '%s' not loaded — skipping session %s",
                       risk_profile, session)
        return

    # ── Get signal ────────────────────────────────────────────────────────────
    try:
        from trading.trading_bot.data.fetcher    import load_all
        from trading.trading_bot.data.processor  import process_all
        from trading.trading_bot.env.trading_env import TradingEnv

        raw_data  = load_all()
        processed = process_all(raw_data)

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
        action_int    = int(action_int)
        action        = ["Hold", "Buy", "Sell"][action_int]
        current_price = Decimal(str(processed[ticker]["close"].iloc[-1]))

    except Exception as exc:
        logger.error("Signal generation failed for %s/%s: %s",
                     ticker, risk_profile, exc)
        return

    # Reload session to get latest budget_remaining (avoid stale data)
    session.refresh_from_db()

    # ── Log Hold and skip ─────────────────────────────────────────────────────
    if action == "Hold":
        RobotTrade.objects.create(
            session        = session,
            user           = user,
            symbol         = ticker,
            action         = "Hold",
            price          = current_price,
            shares         = Decimal("0"),
            balance_before = session.budget_remaining,
            balance_after  = session.budget_remaining,
            note           = "Robot held position",
        )
        logger.info("[%s] %s → HOLD @ $%s", user.email, ticker, current_price)
        return

    # ── Execute Buy ───────────────────────────────────────────────────────────
    if action == "Buy":
        # Spend up to the full budget_remaining — buy as many whole shares as possible
        max_shares = session.budget_remaining // current_price
        cost       = max_shares * current_price

        if max_shares <= 0:
            logger.info("[%s] %s → BUY skipped (insufficient budget: $%s)",
                        user.email, ticker, session.budget_remaining)
            return

        budget_before = session.budget_remaining
        session.budget_remaining -= cost
        session.save(update_fields=["budget_remaining"])

        # Also deduct from demo_balance so portfolio stays in sync
        user.demo_balance -= cost
        user.save(update_fields=["demo_balance"])

        position, created = Position.objects.get_or_create(
            user=user, symbol=ticker,
            defaults={"shares": max_shares, "avg_buy_price": current_price}
        )
        if not created:
            total_shares = position.shares + max_shares
            position.avg_buy_price = (
                (position.shares * position.avg_buy_price + max_shares * current_price)
                / total_shares
            )
            position.shares = total_shares
            position.save()

        RobotTrade.objects.create(
            session        = session,
            user           = user,
            symbol         = ticker,
            action         = "Buy",
            price          = current_price,
            shares         = max_shares,
            balance_before = budget_before,
            balance_after  = session.budget_remaining,
            note           = f"Robot bought {max_shares} shares (budget: ${session.budget})",
        )
        logger.info("[%s] %s → BUY %s @ $%s (budget remaining: $%s)",
                    user.email, ticker, max_shares, current_price, session.budget_remaining)

    # ── Execute Sell ──────────────────────────────────────────────────────────
    elif action == "Sell":
        try:
            position = Position.objects.get(user=user, symbol=ticker)
        except Position.DoesNotExist:
            logger.info("[%s] %s → SELL skipped (no position)", user.email, ticker)
            return

        shares_to_sell = position.shares
        proceeds       = shares_to_sell * current_price
        budget_before  = session.budget_remaining

        # Return proceeds to session budget and demo_balance
        session.budget_remaining += proceeds
        session.save(update_fields=["budget_remaining"])

        user.demo_balance += proceeds
        user.save(update_fields=["demo_balance"])

        position.delete()

        RobotTrade.objects.create(
            session        = session,
            user           = user,
            symbol         = ticker,
            action         = "Sell",
            price          = current_price,
            shares         = shares_to_sell,
            balance_before = budget_before,
            balance_after  = session.budget_remaining,
            note           = f"Robot sold {shares_to_sell} shares (budget: ${session.budget})",
        )
        logger.info("[%s] %s → SELL %s @ $%s (budget remaining: $%s)",
                    user.email, ticker, shares_to_sell, current_price, session.budget_remaining)