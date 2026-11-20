# Technical Analyzer Lambda

import json
import pandas as pd
import numpy as np


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_sma(series, period=14):
    return series.rolling(period).mean()


def calculate_ema(series, period=14):
    return series.ewm(span=period, adjust=False).mean()


def calculate_macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal
    return macd, signal, histogram


def lambda_handler(event, context):
    print("=== TechnicalAnalyzerLambda ===")
    print(json.dumps(event, indent=2))

    symbol = str(event.get("symbol", "AAPL")).upper()
    indicator = str(event.get("indicator", "RSI")).upper()
    period = int(event.get("period", 14))

    data = event.get("data")
    if not isinstance(data, list):
        return {"error": "Missing 'data' list"}

    df = pd.DataFrame(data).sort_values("date")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    close = df["close"]

    if indicator == "RSI":
        rsi = calculate_rsi(close, period)
        val = float(rsi.iloc[-1])
        if val > 70:
            signal = "Overbought"
        elif val < 30:
            signal = "Oversold"
        else:
            signal = "Neutral"

        return {"symbol": symbol, "indicator": "RSI", "value": val, "signal": signal}

    if indicator == "SMA":
        sma = calculate_sma(close, period)
        val = float(sma.iloc[-1])
        signal = "Bullish" if close.iloc[-1] > val else "Bearish"
        return {"symbol": symbol, "indicator": "SMA", "value": val, "signal": signal}

    if indicator == "EMA":
        ema = calculate_ema(close, period)
        val = float(ema.iloc[-1])
        signal = "Bullish" if close.iloc[-1] > val else "Weak"
        return {"symbol": symbol, "indicator": "EMA", "value": val, "signal": signal}

    if indicator == "MACD":
        macd, sig, hist = calculate_macd(close)
        return {
            "symbol": symbol,
            "indicator": "MACD",
            "value": {
                "macd": float(macd.iloc[-1]),
                "signal": float(sig.iloc[-1]),
                "histogram": float(hist.iloc[-1]),
            },
            "signal": "Bullish" if hist.iloc[-1] > 0 else "Bearish"
        }

    return {"error": f"Unknown indicator '{indicator}'"}
