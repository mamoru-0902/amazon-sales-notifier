import os
import requests
from datetime import datetime
import pytz
import json

LWA_CLIENT_ID = os.environ["LWA_CLIENT_ID"]
LWA_CLIENT_SECRET = os.environ["LWA_CLIENT_SECRET"]
LWA_REFRESH_TOKEN = os.environ["LWA_REFRESH_TOKEN"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

MARKETPLACE_ID = "ATVPDKIKX0DER"
SKU = "SH-TTDagashi30-Minibox-v2"

def get_access_token():
    url = "https://api.amazon.com/auth/o2/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": LWA_REFRESH_TOKEN,
        "client_id": LWA_CLIENT_ID,
        "client_secret": LWA_CLIENT_SECRET,
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    return response.json()["access_token"]

def send_slack(message):
    requests.post(SLACK_WEBHOOK_URL, json={"text": message})

def main():
    access_token = get_access_token()

    # タイムスタンプ取得
    pt = pytz.timezone("America/Los_Angeles")
    timestamp = datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # FBA在庫APIリクエスト
    url = "https://sellingpartnerapi-na.amazon.com/fba/inventory/v1/summaries"
    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json",
    }
    params = {
        "details": "true",
        "granularityType": "Marketplace",
        "granularityId": MARKETPLACE_ID,
        "marketplaceIds": MARKETPLACE_ID,
        "sellerSkus": SKU,
    }

    response = requests.get(url, headers=headers, params=params)

    # Request IDを取得
    request_id = response.headers.get("x-amzn-RequestId", "Not found")

    msg = f"🔍 Amazon Support用デバッグ情報\n\n"
    msg += f"**Application ID:**\namzn1.sp.solution.f3f0972e-32ab-4df9-866e-c1b2ef87b563\n\n"
    msg += f"**Timestamp:**\n{timestamp}\n\n"
    msg += f"**Request URL:**\n{url}\n\n"
    msg += f"**Request Headers:**\nx-amz-access-token: [REDACTED]\nContent-Type: application/json\n\n"
    msg += f"**Request Params:**\n{json.dumps(params, indent=2)}\n\n"
    msg += f"**Response Status:**\n{response.status_code}\n\n"
    msg += f"**Request ID:**\n{request_id}\n\n"
    msg += f"**Response Body:**\n{response.text[:500]}\n"

    print(msg)
    send_slack(msg)

if __name__ == "__main__":
    main()
