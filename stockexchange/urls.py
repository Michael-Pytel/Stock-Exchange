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

    # ML Models
    path("forecast/<str:symbol>/", views.forecast_json, name="forecast_json"),
    path('ml-models/', views.ml_models, name='ml_models'),

    # Trading Bot
    path("robot/",              views.robot_view, name="robot"),
    path("robot/<str:ticker>/", views.robot_view, name="robot_ticker"),
    path("api/robot/",          views.robot_api,  name="robot_api"),
    path("api/robot/deploy/",          views.robot_deploy,  name="robot_deploy"),
    path("api/robot/stop/",            views.robot_stop,    name="robot_stop"),
    path("api/robot/history/",         views.robot_history, name="robot_history"),
    path("api/robot/history/<str:ticker>/", views.robot_history, name="robot_history_ticker"),
    path('api/robot/backtest/', views.robot_backtest_public, name='robot_backtest_public'),
]