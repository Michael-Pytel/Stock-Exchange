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

from decouple import config
from .models import CustomUser, Position

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
    "1D":  (1,    "5Min",  78,  "HH:MM"),
    "1W":  (7,    "1Hour", 120, "date"),
    "1M":  (30,   "1Day",  30,  "date"),
    "3M":  (90,   "1Day",  90,  "date"),
    "YTD": (None, "1Day",  365, "date"),
    "1Y":  (365,  "1Day",  365, "date"),
    "5Y":  (1825, "1Week", 260, "date"),
    "ALL": (3650, "1Month",120, "date"),
}


# ── Home ─────────────────────────────────────────────────────────
def home(request):
    return render(request, "trading/home.html", {"stocks": STOCKS})


# ── Stock Data API ───────────────────────────────────────────────
def stock_data(request, symbol):
    symbol = symbol.upper()
    if symbol not in STOCKS:
        return JsonResponse({"error": "Invalid symbol"}, status=400)

    tf = request.GET.get("tf", "1M").upper()
    if tf not in TIMEFRAME_CONFIG:
        tf = "1M"

    delta_days, alpaca_tf, limit, _ = TIMEFRAME_CONFIG[tf]
    end   = datetime.utcnow()
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
        resp = requests.get(
            f"{ALPACA_DATA_URL}/stocks/{symbol}/bars",
            headers=headers, params=params, timeout=10,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])

        def fmt(t):
            if tf == "1D":              return t[11:16]
            elif tf in ("5Y", "ALL"):   return t[:7]
            else:                       return t[:10]

        result = [{"t": fmt(b["t"]), "c": b["c"], "o": b["o"], "h": b["h"], "l": b["l"]} for b in bars]
        return JsonResponse({"symbol": symbol, "bars": result, "tf": tf})
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

    # Get user's position in this stock (if any)
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

    # Enrich each position with live price
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
        "positions":     enriched,
        "balance":       request.user.demo_balance,
        "total_value":   float(total_value),
        "total_invested":float(total_invested),
        "total_pnl":     float(total_pnl),
        "total_pnl_pct": total_pnl_pct,
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

    price   = Decimal(str(price))
    cost    = shares * price
    user    = request.user

    if user.demo_balance < cost:
        return JsonResponse({"error": "Insufficient demo balance."}, status=400)

    # Update or create position (average up)
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

    price   = _get_latest_price(symbol)
    if price is None:
        return JsonResponse({"error": "Could not fetch current price."}, status=503)

    price   = Decimal(str(price))
    proceeds = shares * price
    user    = request.user

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