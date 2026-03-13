import requests
from decimal import Decimal
from datetime import datetime, timedelta

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.decorators import login_required
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.http import require_POST
from autogluon.timeseries import TimeSeriesPredictor, TimeSeriesDataFrame
import plotly.graph_objects as go
import pandas as pd
import os
from django.conf import settings

from decouple import config
from .models import CustomUser, Position

# ----------------Autogluon models -----------------
AUTOGLUON_MODEL_PATH = os.path.join(settings.BASE_DIR, "trading", "autogluon_models", "gluon_models")
_predictor_cache = None

# ── Alpaca ──────────────────────────────────────────────────────
ALPACA_API_KEY    = config("ALPACA_API_KEY")
ALPACA_SECRET_KEY = config("ALPACA_SECRET_KEY")
ALPACA_DATA_URL   = "https://data.alpaca.markets/v2"

STOCKS = ["AAPL", "AMZN", "GOOGL", "JPM", "META", "MSFT", "NVDA", "TSLA", "V"]

COMPANY_NAMES = {
    "AAPL":  "Apple Inc.",
    "AMZN":  "Amazon.com Inc.",
    "GOOGL": "Alphabet Inc.",
    "JPM":   "JPMorgan Chase & Co.",
    "META":  "Meta Platforms Inc.",
    "MSFT":  "Microsoft Corporation",
    "NVDA":  "NVIDIA Corporation",
    "TSLA":  "Tesla Inc.",
    "V":     "Visa Inc.",
}

TIMEFRAME_CONFIG = {
    "1D":  (1,    "5Min",   390,  "HH:MM"),
    "1W":  (7,    "1Hour",  168,  "date"),
    "1M":  (30,   "1Day",   31,   "date"),
    "3M":  (90,   "1Day",   92,   "date"),
    "YTD": (None, "1Day",   365,  "date"),
    "1Y":  (365,  "1Day",   365,  "date"),
    "5Y":  (1825, "1Week",  261,  "date"),
    "ALL": (7300, "1Month", 1000, "date"),
}


# ── Home ─────────────────────────────────────────────────────────
def home(request):
    import json
    return render(request, "trading/home.html", {"stocks": STOCKS, "stocks_json": json.dumps(STOCKS)})


# ── Stock Data API ───────────────────────────────────────────────
def stock_data(request, symbol):
    symbol = symbol.upper()
    if symbol not in STOCKS:
        return JsonResponse({"error": "Invalid symbol"}, status=400)

    tf = request.GET.get("tf", "1M").upper()
    if tf not in TIMEFRAME_CONFIG:
        tf = "1M"

    delta_days, alpaca_tf, limit, _ = TIMEFRAME_CONFIG[tf]

    before_str = request.GET.get("before")
    if before_str:
        try:
            end = datetime.fromisoformat(before_str.replace("Z", ""))
        except ValueError:
            end = datetime.utcnow()
    else:
        end = datetime.utcnow()

    start = datetime(end.year, 1, 1) if tf == "YTD" else end - timedelta(days=delta_days)

    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    params = {
        "start":      start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end":        end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timeframe":  alpaca_tf,
        "limit":      limit,
        "feed":       "iex",
        "adjustment": "split",
    }

    try:
        # For long timeframes IEX only goes back to 2020-07-01.
        # The robot's fetcher already downloaded full history as parquet — use that.
        if tf in ("ALL", "5Y"):
            import glob
            bot_path = config("TRADING_BOT_PATH")
            data_dir = os.path.join(bot_path, "market_data")
            parquet  = os.path.join(data_dir, f"{symbol}.parquet")
            if not os.path.exists(parquet):
                raise ValueError(f"No parquet data found for {symbol} at {parquet}")

            df = pd.read_parquet(parquet)
            # date is a plain column, not the index
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()

            # Resample: monthly for ALL, weekly for 5Y
            freq = "ME" if tf == "ALL" else "W"
            df_rs = df["close"].resample(freq).ohlc()
            df_rs["volume"] = df["volume"].resample(freq).sum()

            if tf == "5Y":
                cutoff = pd.Timestamp.now() - pd.DateOffset(years=5)
                df_rs  = df_rs[df_rs.index >= cutoff]

            result = [
                {
                    "t": idx.isoformat(),
                    "o": round(float(row["open"]),  4),
                    "h": round(float(row["high"]),  4),
                    "l": round(float(row["low"]),   4),
                    "c": round(float(row["close"]), 4),
                    "v": int(row["volume"]),
                }
                for idx, row in df_rs.iterrows()
                if not pd.isna(row["close"])
            ]
            return JsonResponse({"symbol": symbol, "bars": result, "tf": tf, "has_more": False})

        resp = requests.get(
            f"{ALPACA_DATA_URL}/stocks/{symbol}/bars",
            headers=headers, params=params, timeout=10,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])

        result = [{"t": b["t"], "c": b["c"], "o": b["o"], "h": b["h"], "l": b["l"], "v": b.get("v", 0)} for b in bars]
        return JsonResponse({"symbol": symbol, "bars": result, "tf": tf, "has_more": len(bars) >= limit})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ── Latest price helper ──────────────────────────────────────────
def _get_latest_price(symbol):
    """Fetch the most recent close price for a symbol via Alpaca."""
    end   = datetime.utcnow()
    start = end - timedelta(days=5)
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    params = {
        "start":      start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end":        end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timeframe":  "1Day",
        "limit":      5,
        "feed":       "iex",
        "adjustment": "split",
    }
    try:
        resp = requests.get(
            f"{ALPACA_DATA_URL}/stocks/{symbol}/bars",
            headers=headers, params=params, timeout=10,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
        if bars:
            return float(bars[-1]["c"])
    except Exception:
        pass
    return None


# ── Trading page ─────────────────────────────────────────────────
@login_required(login_url="/login/")
def trading_view(request, symbol="AAPL"):
    symbol = symbol.upper()
    if symbol not in STOCKS:
        symbol = "AAPL"

    try:
        position = Position.objects.get(user=request.user, symbol=symbol)
    except Position.DoesNotExist:
        position = None

    context = {
        "stocks":        STOCKS,
        "symbol":        symbol,
        "company":       COMPANY_NAMES.get(symbol, symbol),
        "company_names": COMPANY_NAMES,
        "position":      position,
        "balance":       request.user.demo_balance,
        "show_disclaimer": not request.user.disclaimer_accepted,
    }
    return render(request, "trading/trading_page.html", context)


# ── Disclaimer accept ────────────────────────────────────────────
@login_required(login_url="/login/")
@require_POST
def accept_disclaimer(request):
    request.user.disclaimer_accepted = True
    request.user.save(update_fields=["disclaimer_accepted"])
    return JsonResponse({"ok": True})


# ── Portfolio page ───────────────────────────────────────────────
@login_required(login_url="/login/")
def portfolio_view(request):
    positions = Position.objects.filter(user=request.user)

    enriched = []
    total_invested = Decimal("0")
    total_value    = Decimal("0")

    for pos in positions:
        price = _get_latest_price(pos.symbol)
        if price is None:
            price = float(pos.avg_buy_price)

        current_value  = float(pos.shares) * price
        cost           = float(pos.shares) * float(pos.avg_buy_price)
        pnl_dollar     = current_value - cost
        pnl_pct        = (pnl_dollar / cost * 100) if cost else 0

        enriched.append({
            "symbol":        pos.symbol,
            "company":       COMPANY_NAMES.get(pos.symbol, pos.symbol),
            "shares":        float(pos.shares),
            "avg_buy_price": float(pos.avg_buy_price),
            "current_price": price,
            "current_value": current_value,
            "pnl_dollar":    pnl_dollar,
            "pnl_pct":       pnl_pct,
            "is_up":         pnl_dollar >= 0,
        })

        total_invested += Decimal(str(cost))
        total_value    += Decimal(str(current_value))

    total_pnl     = total_value - total_invested
    total_pnl_pct = (float(total_pnl) / float(total_invested) * 100) if total_invested else 0

    context = {
        "positions":      enriched,
        "balance":        request.user.demo_balance,
        "total_value":    float(total_value),
        "total_invested": float(total_invested),
        "total_pnl":      float(total_pnl),
        "total_pnl_pct":  total_pnl_pct,
        "portfolio_total": float(request.user.demo_balance) + float(total_value),
    }
    return render(request, "trading/portfolio.html", context)


# ── Buy ──────────────────────────────────────────────────────────
@login_required(login_url="/login/")
@require_POST
def buy_stock(request):
    symbol = request.POST.get("symbol", "").upper()
    try:
        shares = Decimal(str(request.POST.get("shares", "0")))
    except Exception:
        return JsonResponse({"error": "Invalid share quantity."}, status=400)

    if symbol not in STOCKS:
        return JsonResponse({"error": "Invalid symbol."}, status=400)
    if shares <= 0:
        return JsonResponse({"error": "Share quantity must be positive."}, status=400)

    price = _get_latest_price(symbol)
    if price is None:
        return JsonResponse({"error": "Could not fetch current price."}, status=503)

    price = Decimal(str(price))
    cost  = shares * price
    user  = request.user

    if user.demo_balance < cost:
        return JsonResponse({"error": "Insufficient demo balance."}, status=400)

    pos, created = Position.objects.get_or_create(
        user=user, symbol=symbol,
        defaults={"shares": shares, "avg_buy_price": price},
    )
    if not created:
        total_shares = pos.shares + shares
        pos.avg_buy_price = (
            (pos.shares * pos.avg_buy_price) + (shares * price)
        ) / total_shares
        pos.shares = total_shares
        pos.save()

    user.demo_balance -= cost
    user.save(update_fields=["demo_balance"])

    return JsonResponse({
        "ok":      True,
        "balance": float(user.demo_balance),
        "shares":  float(pos.shares),
        "avg":     float(pos.avg_buy_price),
    })


# ── Sell ─────────────────────────────────────────────────────────
@login_required(login_url="/login/")
@require_POST
def sell_stock(request):
    symbol = request.POST.get("symbol", "").upper()
    try:
        shares = Decimal(str(request.POST.get("shares", "0")))
    except Exception:
        return JsonResponse({"error": "Invalid share quantity."}, status=400)

    if symbol not in STOCKS:
        return JsonResponse({"error": "Invalid symbol."}, status=400)
    if shares <= 0:
        return JsonResponse({"error": "Share quantity must be positive."}, status=400)

    try:
        pos = Position.objects.get(user=request.user, symbol=symbol)
    except Position.DoesNotExist:
        return JsonResponse({"error": "No position in this stock."}, status=400)

    if shares > pos.shares:
        return JsonResponse({"error": "Not enough shares to sell."}, status=400)

    price = _get_latest_price(symbol)
    if price is None:
        return JsonResponse({"error": "Could not fetch current price."}, status=503)

    price    = Decimal(str(price))
    proceeds = shares * price
    user     = request.user

    pos.shares -= shares
    if pos.shares == 0:
        pos.delete()
        remaining_shares = 0
        avg = 0
    else:
        pos.save()
        remaining_shares = float(pos.shares)
        avg = float(pos.avg_buy_price)

    user.demo_balance += proceeds
    user.save(update_fields=["demo_balance"])

    return JsonResponse({
        "ok":      True,
        "balance": float(user.demo_balance),
        "shares":  remaining_shares,
        "avg":     avg,
    })


# ── Auth helpers ─────────────────────────────────────────────────
def _make_uid_token(user):
    uid   = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return uid, token

def _build_url(request, name, uidb64, token):
    return request.build_absolute_uri(reverse(name, kwargs={"uidb64": uidb64, "token": token}))


# ── Register ─────────────────────────────────────────────────────
def register_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name  = request.POST.get("last_name",  "").strip()
        email      = request.POST.get("email",      "").strip().lower()
        password1  = request.POST.get("password1",  "")
        password2  = request.POST.get("password2",  "")

        if not all([first_name, last_name, email, password1, password2]):
            messages.error(request, "All fields are required.")
            return render(request, "trading/register.html")
        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, "trading/register.html")
        if len(password1) < 8:
            messages.error(request, "Password must be at least 8 characters.")
            return render(request, "trading/register.html")
        if CustomUser.objects.filter(email=email).exists():
            messages.error(request, "An account with this email already exists.")
            return render(request, "trading/register.html")

        user = CustomUser.objects.create_user(
            email=email,
            password=password1,
            first_name=first_name,
            last_name=last_name,
        )

        uid, token = _make_uid_token(user)
        link = _build_url(request, "verify_email", uid, token)

        print("\n" + "="*60)
        print("  EMAIL VERIFICATION")
        print("="*60)
        print(f"  To: {email}")
        print(f"  Name: {first_name} {last_name}")
        print(f"  Verify link: {link}")
        print("="*60 + "\n")

        messages.success(request, "Account created! Check the console for your verification link.")
        return redirect("login")

    return render(request, "trading/register.html")


# ── Email Verification ───────────────────────────────────────────
def verify_email(request, uidb64, token):
    try:
        uid  = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        user = None

    if user and default_token_generator.check_token(user, token):
        user.activate()
        messages.success(request, "Email verified! You can now log in.")
    else:
        messages.error(request, "Verification link is invalid or has expired.")

    return redirect("login")


# ── Login ─────────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect("trading")

    if request.method == "POST":
        email    = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        remember = request.POST.get("remember")

        user = authenticate(request, username=email, password=password)
        if user is None:
            try:
                u = CustomUser.objects.get(email=email)
                user = authenticate(request, username=u.username, password=password)
            except CustomUser.DoesNotExist:
                pass

        if user:
            if not user.is_active:
                messages.error(request, "Please verify your email before logging in.")
            else:
                login(request, user)
                if not remember:
                    request.session.set_expiry(0)
                return redirect("trading")
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, "trading/login.html")


# ── Logout ────────────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    return redirect("home")


# ── Forgot Password ───────────────────────────────────────────────
def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        try:
            user = CustomUser.objects.get(email=email, is_active=True)
            uid, token = _make_uid_token(user)
            link = _build_url(request, "reset_password", uid, token)
            print("\n" + "="*60)
            print("  PASSWORD RESET")
            print("="*60)
            print(f"  To: {email}")
            print(f"  Reset link: {link}")
            print("="*60 + "\n")
        except CustomUser.DoesNotExist:
            pass

        messages.success(request, "If that email exists, a reset link has been printed to the console.")
        return redirect("forgot_password")

    return render(request, "trading/forgot_password.html")


# ── Reset Password ────────────────────────────────────────────────
def reset_password(request, uidb64, token):
    try:
        uid  = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        user = None

    if not user or not default_token_generator.check_token(user, token):
        messages.error(request, "Reset link is invalid or has expired.")
        return redirect("forgot_password")

    if request.method == "POST":
        p1 = request.POST.get("password1", "")
        p2 = request.POST.get("password2", "")
        if p1 != p2:
            messages.error(request, "Passwords do not match.")
        elif len(p1) < 8:
            messages.error(request, "Password must be at least 8 characters.")
        else:
            user.set_password(p1)
            user.save()
            messages.success(request, "Password reset successfully. You can now log in.")
            return redirect("login")

    return render(request, "trading/reset_password.html", {"uidb64": uidb64, "token": token})


# ── Autogluon model load ──────────────────────────────────────────
def _get_predictor():
    global _predictor_cache
    if _predictor_cache is None:
        _predictor_cache = TimeSeriesPredictor.load(AUTOGLUON_MODEL_PATH)
    return _predictor_cache


def _fetch_for_autogluon(ticker, past_days=1200):
    from autogluon.timeseries import TimeSeriesDataFrame
    import pandas as pd
    end   = datetime.utcnow()
    start = end - timedelta(days=past_days)

    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    params = {
        "start":     start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end":       end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timeframe": "1Day",
        "limit":     past_days,
        "feed":      "iex",
    }

    resp = requests.get(
        f"{ALPACA_DATA_URL}/stocks/{ticker}/bars",
        headers=headers, params=params, timeout=60,
    )
    resp.raise_for_status()
    bars = resp.json().get("bars", [])
    if not bars:
        raise ValueError(f"Brak danych dla {ticker}")

    df = pd.DataFrame(bars).rename(columns={
        "t": "timestamp", "o": "open", "h": "high",
        "l": "low",       "c": "close", "v": "volume",
    })
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"], utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
    )
    df["ticker"] = ticker

    import sys
    autogluon_dir = os.path.join(settings.BASE_DIR, "trading", "autogluon_models")
    if autogluon_dir not in sys.path:
        sys.path.insert(0, autogluon_dir)

    from trading.autogluon_models.preprocessing import add_features
    df = add_features(df)

    ts_data = TimeSeriesDataFrame.from_data_frame(
        df, id_column="ticker", timestamp_column="timestamp"
    )
    return ts_data


@login_required(login_url="/login/")
def forecast_json(request, symbol="AAPL"):
    import pandas as pd

    symbol = symbol.upper()
    if symbol not in STOCKS:
        return JsonResponse({"error": "Invalid symbol"}, status=400)

    try:
        predictor  = _get_predictor()
        ts_data    = _fetch_for_autogluon(symbol)
        forecast   = predictor.predict(ts_data)

        history    = ts_data.loc[symbol].tail(20)
        future     = forecast.loc[symbol]
        target_col = predictor.target

        history_out = [
            {"date": str(idx.date()), "value": round(float(row[target_col]), 6)}
            for idx, row in history.iterrows()
        ]

        forecast_out = []
        for idx, row in future.iterrows():
            forecast_out.append({
                "date":   str(idx.date()),
                "q005":   round(float(row["0.05"]),  6),
                "q01":    round(float(row["0.1"]),   6),
                "q03":    round(float(row["0.3"]),   6),
                "median": round(float(row["0.5"]),   6),
                "q07":    round(float(row["0.7"]),   6),
                "q09":    round(float(row["0.9"]),   6),
                "q095":   round(float(row["0.95"]),  6),
            })

        last_val = history_out[-1]["value"]

        return JsonResponse({
            "symbol":   symbol,
            "history":  history_out,
            "forecast": forecast_out,
            "last_val": last_val,
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def robot_view(request, ticker="AAPL"):
    ticker = ticker.upper()
    if ticker not in STOCKS:
        ticker = "AAPL"
    return render(request, "trading/robot.html", {
        "stocks":   STOCKS,
        "symbol":   ticker,
        "company":  COMPANY_NAMES.get(ticker, ticker),
        "balance":  request.user.demo_balance,
    })


def robot_backtest_public(request):
    """Public endpoint — backtest only, no signal (no auth required).
       Used by the homepage to show real training results to all visitors."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    import json
    from trading.robot_engine import get_backtest

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    ticker       = body.get("ticker", "AAPL").upper()
    risk_profile = body.get("risk_profile", "aggressive")

    if ticker not in STOCKS:
        return JsonResponse({"error": f"Unknown ticker: {ticker}"}, status=400)
    if risk_profile not in ("aggressive", "conservative"):
        return JsonResponse({"error": "risk_profile must be aggressive or conservative"}, status=400)

    return JsonResponse(get_backtest(ticker, risk_profile))


@login_required
def robot_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    import json
    from trading.robot_engine import get_signal, get_backtest

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    ticker       = body.get("ticker", "AAPL").upper()
    risk_profile = body.get("risk_profile", "aggressive")
    mode         = body.get("mode", "signal")

    if ticker not in STOCKS:
        return JsonResponse({"error": f"Unknown ticker: {ticker}"}, status=400)
    if risk_profile not in ("aggressive", "conservative"):
        return JsonResponse({"error": "risk_profile must be aggressive or conservative"}, status=400)

    if mode == "signal":
        return JsonResponse(get_signal(ticker, risk_profile))
    elif mode == "backtest":
        return JsonResponse(get_backtest(ticker, risk_profile))
    else:
        return JsonResponse({"error": f"Unknown mode: {mode}"}, status=400)


import csv
import os
from django.shortcuts import render
from django.conf import settings

CSV_DIR = os.path.join(settings.BASE_DIR, "trading", "static", "trading", "csv")


def _read_csv(filename):
    path = os.path.join(CSV_DIR, filename)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ml_models(request):
    backtest_rows  = _read_csv("backtest_summary.csv")
    hit_ratio_rows = _read_csv("hit_ratio_backtest.csv")
    winkler_rows   = _read_csv("winkler_per_ticker.csv")
    coverage_rows  = _read_csv("coverage_results.csv")

    hit_map     = {r["Ticker"]: float(r["Hit Ratio"]) for r in hit_ratio_rows}
    winkler_map = {r["item_id"]: r                    for r in winkler_rows}

    ticker_data = {}
    for row in backtest_rows:
        ticker = row["Ticker"]
        w      = winkler_map.get(ticker, {})
        ticker_data[ticker] = {
            "mase":         float(row["Mean_MASE"]),
            "rmse":         float(row["Mean_RMSE"]),
            "wql":          float(row["Mean WQL"]),
            "hit_ratio":    hit_map.get(ticker, 0.0),
            "winkler":      float(w.get("Winkler Score (0.1-0.9)", 0)),
            "winkler_norm": float(w.get("Winkler Normalized", 0)),
        }

    for ticker, d in ticker_data.items():
        hr   = d["hit_ratio"]
        diff = hr - 0.5
        d["hit_ratio_pct"] = f"{hr * 100:.2f}"
        d["hit_color"]     = "good" if hr >= 0.55 else ("bad" if hr < 0.50 else "")
        d["hit_vs_random"] = f"{'+' if diff >= 0 else ''}{diff * 100:.2f}% vs 50%"

    tickers = list(ticker_data.keys())

    raw_weights = [
        {"model": "RecursiveTabular",           "type": "Gradient Boosting",  "weight": 0.448},
        {"model": "Temporal Fusion Transformer","type": "Transformer",        "weight": 0.276},
        {"model": "DeepAR",                     "type": "Probabilistic RNN",  "weight": 0.241},
        {"model": "PatchTST",                   "type": "Transformer",        "weight": 0.034},
    ]
    max_w = max(w["weight"] for w in raw_weights)
    ensemble_weights = [
        {**w,
         "width_pct": round(w["weight"] / max_w * 100, 1),
         "pct_label": f"{w['weight']*100:.1f}%"}
        for w in raw_weights
    ]

    cov = coverage_rows[0]
    coverage = [
        {"level": "α = 0.05", "actual": float(cov["Coverage Actual (0.05)"]), "error": float(cov["Coverage Error (0.05)"])},
        {"level": "α = 0.10", "actual": float(cov["Coverage Actual (0.1)"]),  "error": float(cov["Coverage Error (0.1)"])},
        {"level": "α = 0.30", "actual": float(cov["Coverage Actual (0.3)"]),  "error": float(cov["Coverage Error (0.3)"])},
        {"level": "α = 0.90", "actual": float(cov["Coverage Actual (0.9)"]),  "error": float(cov["Coverage Error (0.9)"])},
    ]

    for c in coverage:
        c["actual_pct"]  = f"{c['actual'] * 100:.2f}"
        c["error_pct"]   = f"{abs(c['error']) * 100:.2f}"
        c["error_sign"]  = "+" if c["error"] >= 0 else "−"
        c["error_class"] = "bad" if c["error"] > 0.01 else "good"

    return render(request, "trading/ml_models.html", {
        "tickers":          tickers,
        "ticker_data":      ticker_data,
        "coverage":         coverage,
        "ensemble_weights": ensemble_weights,
    })


@login_required
def robot_deploy(request):
    from trading.models import RobotSession

    if request.method == "GET":
        sessions = RobotSession.objects.filter(
            user=request.user, is_active=True
        ).values("symbol", "risk_profile", "started_at")
        return JsonResponse({
            "sessions": [
                {
                    "symbol":       s["symbol"],
                    "risk_profile": s["risk_profile"],
                    "started_at":   s["started_at"].strftime("%Y-%m-%d %H:%M"),
                }
                for s in sessions
            ]
        })

    if request.method == "POST":
        import json
        body         = json.loads(request.body)
        ticker       = body.get("ticker", "").upper()
        risk_profile = body.get("risk_profile", "aggressive")

        if ticker not in STOCKS:
            return JsonResponse({"error": f"Unknown ticker: {ticker}"}, status=400)
        if risk_profile not in ("aggressive", "conservative"):
            return JsonResponse({"error": "Invalid risk_profile"}, status=400)

        session, created = RobotSession.objects.update_or_create(
            user=request.user, symbol=ticker,
            defaults={
                "risk_profile": risk_profile,
                "is_active":    True,
                "stopped_at":   None,
            }
        )
        return JsonResponse({
            "status":  "deployed",
            "ticker":  ticker,
            "profile": risk_profile,
            "created": created,
        })

    return JsonResponse({"error": "GET or POST required"}, status=405)


@login_required
def robot_stop(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    import json
    from django.utils import timezone
    from trading.models import RobotSession

    body   = json.loads(request.body)
    ticker = body.get("ticker", "").upper()

    updated = RobotSession.objects.filter(
        user=request.user, symbol=ticker, is_active=True
    ).update(is_active=False, stopped_at=timezone.now())

    if updated:
        return JsonResponse({"status": "stopped", "ticker": ticker})
    return JsonResponse({"error": "No active session found"}, status=404)


@login_required
def robot_history(request, ticker=None):
    from trading.models import RobotTrade

    qs = RobotTrade.objects.filter(user=request.user).order_by("-timestamp")
    if ticker:
        qs = qs.filter(symbol=ticker.upper())

    trades = [
        {
            "timestamp":      t.timestamp.strftime("%Y-%m-%d %H:%M"),
            "symbol":         t.symbol,
            "action":         t.action,
            "price":          float(t.price),
            "shares":         float(t.shares),
            "balance_before": float(t.balance_before),
            "balance_after":  float(t.balance_after),
            "note":           t.note,
        }
        for t in qs[:100]
    ]
    return JsonResponse({"trades": trades})