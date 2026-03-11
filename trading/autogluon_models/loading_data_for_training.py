import pandas as pd
from datetime import datetime, timedelta
from alpaca_trade_api.rest import REST
from decouple import config
from preprocessing import *
import requests

ALPACA_API_KEY    = config("ALPACA_API_KEY")
ALPACA_SECRET_KEY = config("ALPACA_SECRET_KEY")
ALPACA_DATA_URL = "https://data.alpaca.markets/v2"

STOCKS = ["AAPL", "AMZN", "GOOGL", "JPM", "META", "MSFT", "NVDA", "TSLA", "V"]


def load_all_data_alpaca(tickers = STOCKS):
    """
    Pobiera dane historyczne dla wszystkich tickerów z Alpaca.
    Dodaje cechy z add_features() i zwraca jeden DataFrame.
    """
    all_data_list = []
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }

    for ticker in tickers:
        end = datetime.utcnow()
        start = end - timedelta(1200)

        params = {
       "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timeframe": "1Day",
        "limit": 1200,
        "feed": "iex",
        "adjustment": "split",
        }

        try:
            resp = requests.get(
                f"{ALPACA_DATA_URL}/stocks/{ticker}/bars",
                headers=headers,
                params=params,
                timeout=100,
            )
            resp.raise_for_status()
            data = resp.json()
            bars = data.get("bars", [])

            if not bars:
                print(f"Brak danych dla {ticker}")
                continue

            # Mapowanie do DataFrame
            df = pd.DataFrame(bars)
            df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)  # wymusza UTC
            df['timestamp'] = df['timestamp'].dt.tz_localize(None)       # usuwa strefę czasową
            df['timestamp'] = df['timestamp'].dt.normalize()
            df['ticker'] = ticker

            # Dodanie cech
            df = add_features(df)

            all_data_list.append(df)

        except Exception as e:
            print(f"Błąd pobierania danych dla {ticker}: {e}")
            continue

    
    return pd.concat(all_data_list).sort_values(by=['ticker', 'timestamp']).reset_index(drop=True)
  



