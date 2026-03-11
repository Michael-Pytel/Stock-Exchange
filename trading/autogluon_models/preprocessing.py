import numpy as np
import ta

import numpy as np
import ta


def add_features(data):
    '''
        Adding new features to the yfinance dataframe:
        1. Return (Fractional Change) - 1day, 30 days
        2. Log return - 1day, 30 days
        3. volume change - 1day, 30 days
        4. Moving Average - 5 days, 30 days
        5. Volatility - 5 days, 30 days
        6. RSI - Relative Strength Index
        7. Lagged Closing price - 1 day, 30 days before 

        Returns: 
        Dataframe with removed NaN rows
    
    '''
    
    data = data.copy()

    #high low difference 
    data['high-low'] = data['high']- data['low']

    #open close difference
    data['open-close'] = data['open'] - data['close']

    #Fractional change between the current and a prior element.
    data["Return_1d"] = data['close'].pct_change()
    data["Return_2d"] = data['close'].pct_change(periods=2)
    data["Return_3d"] = data['close'].pct_change(periods=3)
    data["Return_5d"] = data['close'].pct_change(periods=5)
    data["Return_30d"] = data['close'].pct_change(periods=30) #Fractional change between current and before 30 days 

    # Log return
    data["Log_return_1d"] = np.log(data["close"] / data["close"].shift(1))
    data["Log_return_2d"] = np.log(data["close"] / data["close"].shift(2))
    data["Log_return_3d"] = np.log(data["close"] / data["close"].shift(3))
    data["Log_return_5d"] = np.log(data["close"] / data["close"].shift(5))
    data["Log_return_30d"] = np.log(data["close"] / data["close"].shift(30))

    # volume change
    data["volume_change_1d"] = data['volume'].pct_change()
    data["volume_change_2d"] = data['volume'].pct_change(periods=2)
    data["volume_change_5d"] = data['volume'].pct_change(periods=5)
    data['volume_change_30d'] = data['volume'].pct_change(periods=30)
    data['Log_volume'] = np.log1p(data['volume'])

    # Moving/ Rolling average
    data["SMA_5d"]= data['close'].rolling(5).mean()
    data["SMA_2d"]= data['close'].rolling(2).mean()
    data["SMA_8d"]= data['close'].rolling(8).mean()
    data['SMA_30d'] = data['close'].rolling(30).mean()

    # Volatility
    data["volatility_5d"] = data["close"].rolling(5).std()
    data["volatility_2d"] = data["close"].rolling(2).std()
    data["volatility_10d"] = data["close"].rolling(10).std()
    data['Volatility_30d'] = data['close'].rolling(30).std()
    

    # Czy dzisiejsza zmienność jest wysoka na tle ostatnich 20 dni?
    data['Vol_ZScore'] = (data['volatility_5d'] - data['volatility_5d'].rolling(20).mean()) / data['volatility_5d'].rolling(20).std()
    data['Vol_EWMA_10'] = data['Log_return_1d'].ewm(span=10).std()
    # Mierzy, czy ogon rozkładu jest po stronie spadków (ujemny skew)
    data['Skew_20d'] = data['Log_return_1d'].rolling(20).skew()
    # Mierzy prawdopodobieństwo zdarzeń ekstremalnych (tzw. "grube ogony")
    data['Kurt_20d'] = data['Log_return_1d'].rolling(20).kurt()
    # RSI
    data["RSI"] = ta.momentum.RSIIndicator(data["close"]).rsi()
    # RSI + direction
    data['RSI_direction'] = data['RSI'] * np.sign(data['close'].diff()).shift(1)

    # Lagged features
    data["close_lag_1d"] = data["close"].shift(1)
    data["close_lag_2d"] = data["close"].shift(2)
    data["close_lag_3d"] = data["close"].shift(3)
    data["close_lag_5d"] = data["close"].shift(5)
    data["close_lag_10d"] = data["close"].shift(10)
    data['close_lag_30d'] = data["close"].shift(30)

    # Position
    data['Position_in_day'] = (data['close'] - data['low']) / (data['high'] - data['low'])

    # Direction features
    for period in [1, 3, 5, 10, 20]:
        direction = np.sign(data['close'].diff(period))
        data[f'Direction_{period}d'] = direction
        
        rolling_dir = direction.rolling(period)
        data[f'Trend_strength_{period}d'] = abs(rolling_dir.sum()) / period
        
        # Zmiana kierunku (czy trend się odwrócił)
        data[f'Direction_change_{period}d'] = direction.diff()

    data=data.dropna()
    return data


# def create_target(data):
#     data["Target"] = (data["c"].shift(-1) > data["c"]).astype(int)
#     # 1 = jutro cena wyższa, 0 = jutro cena niższa
#     data.dropna(inplace=True)
#     return data