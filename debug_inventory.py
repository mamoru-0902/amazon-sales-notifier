import os
import requests
import pytz
from datetime import datetime

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
    headers = {"x-amz-access-token": access_token}

    # テスト①: SKU指定で取得
    print("=== テスト①: SKU指定 ===")
    url = "https://sellingpartnerapi-na.amazon.com/fba/inventory/v1/summaries"
    params = {
        "details": "true",
        "granularityType": "Marketplace",
        "granularityId": MARKETPLACE_ID,
        "marketplaceIds": MARKETPLACE_ID,
        "sellerSkus": SKU,
    }
    r = requests.get(url, headers=headers, params=params)
    print(f"ステータス: {r.status_code}")
    print(f"レスポンス: {r.text[:500]}")

    # テスト②: 全在庫取得
    print("\n=== テスト②: 全在庫取得 ===")
    params2 = {
        "details": "true",
        "granularityType": "Marketplace",
        "granularityId": MARKETPLACE_ID,
        "marketplaceIds": MARKETPLACE_ID,
    }
    r2 = requests.get(url, headers=headers, params=params2)
    print(f"ステータス: {r2.status_code}")
    data2 = r2.json()
    summaries = data2.get("payload", {}).get("inventorySummaries", [])
    print(f"取得件数: {len(summaries)}")
    for item in summaries[:5]:
        print(f"  SKU: {item.get('sellerSku')}, ASIN: {item.get('asin')}, 数量: {item.get('inventoryDetails', {}).get('fulfillableQuantity')}")

    # Slackにデバッグ結果を送信
    msg = f"🔍 在庫デバッグ結果\n"
    msg += f"テスト① ステータス: {r.status_code}\n"
    msg += f"テスト① レスポンス: {r.text[:200]}\n\n"
    msg += f"テスト② ステータス: {r2.status_code}\n"
    msg += f"テスト② 取得件数: {len(summaries)}\n"
    for item in summaries[:5]:
        msg += f"SKU: {item.get('sellerSku')}, 数量: {item.get('inventoryDetails', {}).get('fulfillableQuantity')}\n"
    send_slack(msg)

if __name__ == "__main__":
    main()
