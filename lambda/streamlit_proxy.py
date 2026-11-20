#Streamlit lambda

import os
import json
import boto3
import re

lambda_client = boto3.client("lambda")
bedrock_agent_rt = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

# --- Bedrock Agent IDs ---
AGENT_ID = os.environ.get("AGENT_ID")
AGENT_ALIAS_ID = os.environ.get("AGENT_ALIAS_ID")

# --- Child Lambdas ---
DATA_FETCHER_ARN = os.environ.get("DATA_FETCHER_ARN")  # set in the Lambda environment variables (ARN scrubbed for public repo)
TECH_ANALYZER_ARN = os.environ.get("TECH_ANALYZER_ARN")  # set in the Lambda environment variables (ARN scrubbed for public repo)
PREDICTOR_ARN = os.environ.get("PREDICTOR_ARN")  # set in the Lambda environment variables (ARN scrubbed for public repo)


def invoke_lambda(arn, payload):
    """Invoke a child Lambda and always return parsed JSON."""
    resp = lambda_client.invoke(
        FunctionName=arn,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8")
    )
    raw = resp["Payload"].read().decode("utf-8")

    try:
        return json.loads(raw)
    except:
        return {"raw": raw}


# ---------------------------
# STREAMLIT / API GATEWAY ENTRY
# ---------------------------
def handle_http_event(event):
    print("=== STREAMLIT EVENT ===")
    print("Event keys:", sorted(event.keys()) if isinstance(event, dict) else type(event).__name__)

    body = event.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except:
            body = {}
    elif body is None:
        body = {}

    prompt = (
        body.get("prompt")
        or body.get("query")
        or body.get("message")
        or event.get("inputText")
        or "Hello"
    )

    session_id = body.get("sessionId") or "streamlit-session"

    print("User prompt received (length):", len(prompt))

    # ---- SEND TO BEDROCK AGENT ----
    response = bedrock_agent_rt.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=AGENT_ALIAS_ID,
        sessionId=session_id,
        inputText=prompt
    )

    final_text = ""
    for chunk in response.get("completion", []):
        if "chunk" in chunk:
            b = chunk["chunk"].get("bytes")
            if b:
                try:
                    final_text += b.decode("utf-8")
                except:
                    final_text += b.decode("latin-1")

    print("=== FINAL AGENT RESPONSE === (length):", len(final_text))

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps({
            "success": True,
            "response": final_text
        })
    }


# ---------------------------
# BEDROCK ACTION TOOL ENTRY
# ---------------------------
def params_list_to_dict(params):
    out = {}
    if isinstance(params, list):
        for p in params:
            name = p.get("name")
            value = p.get("value")
            if name:
                out[name] = value
    return out


def handle_bedrock_action(event):
    print("=== BEDROCK TOOL INVOCATION ===")
    print("Event keys:", sorted(event.keys()) if isinstance(event, dict) else type(event).__name__)

    action_group = event.get("actionGroup")
    function_name = event.get("function")
    params = params_list_to_dict(event.get("parameters", []))

    symbol = (params.get("symbol") or "AAPL").upper().strip()

    # -----------------------
    # fetchData
    # -----------------------
    if function_name == "fetchData":
        df = invoke_lambda(DATA_FETCHER_ARN, {"symbol": symbol})

        if isinstance(df, dict) and "close" in df:
            text = (
                f"As of {df['date']}, {symbol} closed at {df['close']:.2f}.\n"
                f"Recent closes available in history."
            )
        else:
            text = f"Could not fetch data for {symbol}: {df}"

        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": action_group,
                "function": "fetchData",
                "functionResponse": {
                    "responseBody": {"TEXT": {"body": text}}
                }
            }
        }

    # -----------------------
    # calculateIndicator
    # -----------------------
    if function_name == "calculateIndicator":
        indicator = (params.get("indicator") or "RSI").upper()
        period = int(params.get("period") or 14)

        df = invoke_lambda(DATA_FETCHER_ARN, {"symbol": symbol})
        if "history" not in df:
            text = f"Could not fetch data for {symbol}: {df}"
        else:
            ta = invoke_lambda(TECH_ANALYZER_ARN, {
                "symbol": symbol,
                "indicator": indicator,
                "period": period,
                "data": df["history"]
            })
            if "error" in ta:
                text = f"Error computing {indicator}: {ta['error']}"
            else:
                text = (
                    f"{indicator} for {symbol}: {ta['value']}.\n"
                    f"Signal: {ta['signal']}\n"
                    "This is not financial advice."
                )

        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": action_group,
                "function": "calculateIndicator",
                "functionResponse": {
                    "responseBody": {"TEXT": {"body": text}}
                }
            }
        }

    # -----------------------
    # predictTrend
    # -----------------------
    if function_name == "predictTrend":
        timeframe = params.get("timeframe") or "next_week"

        df = invoke_lambda(DATA_FETCHER_ARN, {"symbol": symbol})
        if "history" not in df:
            text = f"Could not fetch price history for {symbol}."
        else:
            indicators = {}
            history = df["history"]

            # Compute multiple indicators for predictor
            for ind, per in [("RSI", 14), ("SMA", 20), ("EMA", 20), ("MACD", 26)]:
                ta = invoke_lambda(TECH_ANALYZER_ARN, {
                    "symbol": symbol,
                    "indicator": ind,
                    "period": per,
                    "data": history
                })
                if "value" in ta:
                    indicators[ind.lower()] = ta["value"]

            pred = invoke_lambda(PREDICTOR_ARN, {
                "symbol": symbol,
                "timeframe": timeframe,
                "history": history,
                "indicators": indicators
            })

            text = (
                f"Prediction for {symbol} ({timeframe}):\n"
                f"- Direction: {pred.get('direction')}\n"
                f"- Expected move: {pred.get('change_range')}\n"
                f"- Reasoning: {pred.get('reasoning')}\n"
                "\nThis is not financial advice."
            )

        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": action_group,
                "function": "predictTrend",
                "functionResponse": {
                    "responseBody": {"TEXT": {"body": text}}
                }
            }
        }

    # Default fallback
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function_name,
            "functionResponse": {
                "responseBody": {"TEXT": {"body": f"Unknown tool: {function_name}"}}
            }
        }
    }


# ---------------------------
# MAIN ENTRYPOINT
# ---------------------------
def lambda_handler(event, context):
    print("=== STREAMLITAPILAMBDA ENTRY ===")
    print("Event keys:", sorted(event.keys()) if isinstance(event, dict) else type(event).__name__)

    # If Bedrock Agent is calling (tool mode)
    if "actionGroup" in event and "function" in event:
        return handle_bedrock_action(event)

    # Otherwise HTTP request from Streamlit
    return handle_http_event(event)
