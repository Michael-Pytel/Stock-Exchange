import plotly.graph_objects as go
from autogluon.timeseries import TimeSeriesPredictor, TimeSeriesDataFrame
import pandas as pd
import requests
from preprocessing import *
from decouple import config
from datetime import datetime, timedelta
ALPACA_API_KEY    = config("ALPACA_API_KEY")
ALPACA_SECRET_KEY = config("ALPACA_SECRET_KEY")
ALPACA_DATA_URL = "https://data.alpaca.markets/v2"

import pandas as pd
from datetime import datetime, timedelta
import requests

ALPACA_API_KEY    = config("ALPACA_API_KEY")
ALPACA_SECRET_KEY = config("ALPACA_SECRET_KEY")
ALPACA_DATA_URL = "https://data.alpaca.markets/v2"

def fetch_ticker_data_alpaca(ticker, past_days=1200):
    """
    Pobiera historyczne dane dzienne dla jednego tickera z Alpaca.
    Zwraca DataFrame gotowy do użycia w AutoGluon TimeSeries.
    """
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }

    end = datetime.utcnow()
    start = end - timedelta(days=past_days)

    params = {
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timeframe": "1Day",
        "limit": past_days,
        "feed": "iex",
    }

    resp = requests.get(
        f"{ALPACA_DATA_URL}/stocks/{ticker}/bars",
        headers=headers,
        params=params,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    bars = data.get("bars", [])

    if not bars:
        raise ValueError(f"Brak danych dla {ticker}")

    df = pd.DataFrame(bars)
    df = df.rename(columns={
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume"
    })
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_localize(None).dt.normalize()
    df['ticker'] = ticker
    df = add_features(df)

    return df

def plot_interactive_continuous_forecast(predictor, ticker, stop_loss, past_days=40):
    # 1. Przygotowanie danych
    df_ticker = fetch_ticker_data_alpaca(ticker)
    ts_data = TimeSeriesDataFrame.from_data_frame(df_ticker, id_column = "ticker", timestamp_column="timestamp")
    forecast = predictor.predict(ts_data)

    history = ts_data.loc[ticker].tail(past_days)
    future = forecast.loc[ticker]
    target_col = predictor.target

    last_date = history.index[-1]
    last_val = history[target_col].iloc[-1]


    hover_texts = []
    for i in range(len(future)):
        row = future.iloc[i]
        text = (
            f"<b>Date: {future.index[i].date()}</b><br>" +
            f"Median: {row['0.5']:.4f}<br>" +
            f"Q 0.3: {row['0.3']:.4f}<br>" +
            f"Q 0.1: {row['0.1']:.4f}<br>" +
            f"<span style='color:red'>Stop Loss: {stop_loss}</span>"
        )
        hover_texts.append(text)

    fig = go.Figure()

    # Stop loss analysis
    alert_x = []
    alert_y = []
    alert_colors = []

    for i in range(len(future)):
        day_date = future.index[i]
        q03 = future["0.3"].iloc[i]
        q01 = future["0.1"].iloc[i]
        q005 = future["0.05"].iloc[i]

        prob_msg = ""
        color = None

        if stop_loss >= q03:
            prob_msg = "HIGH RISK (>Q(0.3))"
            color = "red"
        elif q03 > stop_loss >= q01:
            prob_msg = "MONITOR (Q(0.1)-Q(0.3))"
            color = "#FF8C00"
        elif q01 > stop_loss >= q005:
            prob_msg = "LOW RISK (Q(0.05)-Q(0.1))"
            color = "green"
        else:
            prob_msg = "VERY LOW RISK (< Q(0.05))"

        if color in ["red", "#FF8C00"]:
            alert_x.append(day_date)
            alert_y.append(stop_loss)
            alert_colors.append(color)

        print(f"Dzień: {day_date.date()}  | Q(0.05) = {q005:.3f} | Q(0.1) = {q01:.3f} | Q(0.3) = {q03:.3f} | MSG: {prob_msg}")

    # --- 1. HISTORIA (Czarna linia) ---
    fig.add_trace(go.Scatter(
        x=history.index,
        y=history[target_col],
        name="Historia",
        line=dict(color="black", width=2),
        mode='lines',
        hovertemplate="<b>Historical</b><br>Return: %{y:.4f}<extra></extra>"
    ))


    conn_x = pd.Index([last_date]).append(future.index)
    conn_median = pd.concat([pd.Series([last_val]), future["0.5"]])
    full_hover_texts = ["Punkt wejścia"] + hover_texts

    fig.add_trace(go.Scatter(
        x=conn_x,
        y=conn_median,
        name="Median",
        line=dict(color="#1f77b4", width=3),
        mode='lines',
        text=full_hover_texts, # Przekazujemy nasze opisy
        hovertemplate="%{text}<extra></extra>"
    ))
    # Stop Loss
    fig.add_hline(y=stop_loss, line_dash="dot", line_color="red", layer="below", annotation_text="Stop Loss")

    intervals = [
        ("0.1", "0.9", "rgba(31, 119, 180, 0.25)", "Quatiles 0.1-0.9"),
        ("0.05", "0.95", "rgba(255, 127, 14, 0.15)", "Quantiles 0.05-0.95")
    ]

    for low, high, color, name in intervals:
        if low in future.columns and high in future.columns:
            y_upper = pd.concat([pd.Series([last_val]), future[high]])
            y_lower = pd.concat([pd.Series([last_val]), future[low]])

            fig.add_trace(go.Scatter(
                x=list(conn_x) + list(conn_x)[::-1],
                y=list(y_upper) + list(y_lower)[::-1],
                fill='toself',
                fillcolor=color,
                line=dict(color='rgba(255,255,255,0)'),
                name=name,
                hoverinfo="skip",
                visible=True if "0.1-0.9" in name else "legendonly"
            ))

    fig.update_layout(
        title=f"5 day forecast: {ticker}",
        xaxis_title="Data",
        yaxis_title="Return",
        hovermode="x unified",
        template="plotly_white",
        legend=dict(itemclick="toggle", itemdoubleclick="toggleothers")
    )
    if alert_x:
        fig.add_trace(go.Scatter(
            x=alert_x, y=alert_y,
            mode='markers',
            marker=dict(color=alert_colors, size=6, symbol="circle"),
            name="Alert Stop Loss",

        ))

    return fig



