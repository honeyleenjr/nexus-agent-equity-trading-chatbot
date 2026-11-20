# Data Fetcher Lambda

import json
import boto3
import os
import urllib.request

s3 = boto3.client("s3")


# ==============================================================
# Load API key with fallback: Primary → Backup
# ==============================================================
def load_api_key():
    primary = os.environ.get("SECRET_NAME")               # FinRobot/AlphaVantage
    backup = os.environ.get("SECRET_NAME_BACKUP")         # AIChatBotAgent/API_KEY

    sm = boto3.client("secretsmanager", region_name="us-east-1")

    # ---------- Try PRIMARY secret ----------
    try:
        print(f"Trying primary secret: {primary}")
        sec = sm.get_secret_value(SecretId=primary)["SecretString"]
        data = json.loads(sec)

        api_key = (
            data.get("ALPHAVANTAGE_API_KEY") or
            data.get("API_KEY") or
            list(data.values())[0]
        )

        if api_key:
            print("Primary API key loaded.")
            return api_key

    except Exception as e:
        print(f"Primary secret failed → {e}")

    # ---------- Try BACKUP secret ----------
    try:
        print(f"Trying backup secret: {backup}")
        sec = sm.get_secret_value(SecretId=backup)["SecretString"]
        data = json.loads(sec)

        api_key = (
            data.get("ALPHAVANTAGE_API_KEY") or
            data.get("API_KEY") or
            list(data.values())[0]
        )

        if api_key:
            print("Backup API key loaded.")
            return api_key

    except Exception as e:
        print(f"Backup secret failed → {e}")

    print("❌ NO VALID API KEY FOUND.")
    return None


# ==============================================================
# Extract symbol from ALL formats (Agent + Streamlit + Console)
# ==============================================================
def extract_symbol(event):
    if not isinstance(event, dict):
        return None

    # Bedrock AG → requestBody
    try:
        rb = event.get("requestBody", {})
        props = rb.get("content", {}).get("application/json", {}).get("properties", [])
        for p in props:
            if p.get("name") == "symbol":
                return p.get("value")
    except:
        pass

    # Bedrock AG → parameters
    try:
        for p in event.get("parameters", []):
            if p.get("name") == "symbol":
                return p.get("value")
    except:
        pass

    # Tool input
    if "input" in event and isinstance(event["input"], dict):
        if "symbol" in event["input"]:
            return event["input"]["symbol"]

    # Direct console invoke
    if "symbol" in event:
        return event.get("symbol")

    # API Gateway body
    if "body" in event:
        try:
            body = json.loads(event["body"])
            return body.get("symbol")
        except:
            pass

    return None


# ==============================================================
# MAIN HANDLER
# ==============================================================
def lambda_handler(event, context):
    print("=== DATAFETCHER EVENT ===")
    print(json.dumps(event))

    symbol = extract_symbol(event) or "AAPL"
    symbol = symbol.upper()
    print("Using symbol:", symbol)

    api_key = load_api_key()
    if not api_key:
        return {"error": "Missing AlphaVantage API key."}

    # Build URL
    url = (
        f"https://www.alphavantage.co/query?"
        f"function=TIME_SERIES_DAILY&symbol={symbol}&apikey={api_key}"
    )
    print("Fetching:", url)

    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"FETCH FAILED: {str(e)}"}

    series = data.get("Time Series (Daily)")
    if not series:
        return {"error": f"No stock data returned for {symbol}"}

    dates = sorted(series.keys(), reverse=True)
    last = dates[0]
    close_price = float(series[last]["4. close"])

    result = {
        "symbol": symbol,
        "date": last,
        "close": close_price,
        "history": [
            {"date": d, "close": float(series[d]["4. close"])}
            for d in dates
        ]
    }

    # Save snapshot
    bucket = os.environ.get("S3_BUCKET", "stock-chatbot-data")
    try:
        s3.put_object(
            Bucket=bucket,
            Key=f"history_{symbol}.json",
            Body=json.dumps(result),
            ContentType="application/json"
        )
    except Exception as e:
        print("S3 save error:", e)

    return result
