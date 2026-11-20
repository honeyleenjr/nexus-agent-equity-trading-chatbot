# Predictor Lambda

import json
import boto3
import traceback

bedrock = boto3.client("bedrock-runtime")


def summarise_history(history):
    if not history:
        return "No price history available."

    closes = [float(h["close"]) for h in history]
    first, last = closes[0], closes[-1]
    pct = ((last - first) / first) * 100 if first else 0

    return (
        f"First close: {first}\n"
        f"Last close: {last}\n"
        f"Change: {pct:.2f}%\n"
        f"Recent closes: {closes[-5:]}"
    )


def lambda_handler(event, context):
    print("=== PredictorLambda ===")
    print(json.dumps(event, indent=2))

    symbol = event.get("symbol", "AAPL")
    timeframe = event.get("timeframe", "next_week")
    history = event.get("history", [])
    indicators = event.get("indicators", {})

    summary = summarise_history(history)

    prompt = f"""
You are a conservative financial analyst.

Stock: {symbol}
Timeframe: {timeframe}

Price Summary:
{summary}

Indicators:
{json.dumps(indicators, indent=2)}

Respond ONLY in JSON:
- direction
- change_range
- reasoning
"""

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 400,
        "temperature": 0.2,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": prompt}]}
        ]
    }

    try:
        resp = bedrock.invoke_model(
            modelId="anthropic.claude-3-5-haiku-20241022-v1:0",
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )

        text = json.loads(resp["body"].read())["content"][0]["text"]

        try:
            parsed = json.loads(text)
        except:
            parsed = {"direction": "uncertain", "change_range": "unknown", "reasoning": text}

        parsed["history_summary"] = summary
        parsed["indicators"] = indicators
        parsed["symbol"] = symbol

        return parsed

    except Exception as e:
        print(traceback.format_exc())
        return {
            "symbol": symbol,
            "direction": "uncertain",
            "change_range": "unknown",
            "reasoning": f"Predictor error: {e}",
            "history_summary": summary,
            "indicators": indicators
        }
