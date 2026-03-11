from django.urls import path
from trading import views

urlpatterns = [
    path("",                            views.home,              name="home"),
    path("api/stock/<str:symbol>/",     views.stock_data,        name="stock_data"),

    # Trading
    path("trade/",                      views.trading_view,      name="trading"),
    path("trade/<str:symbol>/",         views.trading_view,      name="trading_symbol"),
    path("portfolio/",                  views.portfolio_view,    name="portfolio"),
    path("api/buy/",                    views.buy_stock,         name="buy_stock"),
    path("api/sell/",                   views.sell_stock,        name="sell_stock"),
    path("api/disclaimer/accept/",      views.accept_disclaimer, name="accept_disclaimer"),

    # Auth
    path("login/",                      views.login_view,        name="login"),
    path("logout/",                     views.logout_view,       name="logout"),
    path("register/",                   views.register_view,     name="register"),
    path("verify/<uidb64>/<token>/",    views.verify_email,      name="verify_email"),
    path("forgot-password/",            views.forgot_password,   name="forgot_password"),
    path("reset/<uidb64>/<token>/",     views.reset_password,    name="reset_password"),

    path("forecast/<str:symbol>/", views.forecast_json, name="forecast_json"),
    path('ml-models/', views.ml_models_view, name='ml_models'),
]