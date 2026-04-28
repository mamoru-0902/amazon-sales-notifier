import os
import requests
import json
from datetime import datetime, timedelta
import pytz

# ==========================================
# 設定：ASINリスト（追加する場合はここに追加）
# ==========================================
ASINS = [
    "B0GKG32M22",
    # 例："B0XXXXXXXXX",  # 新しい商品を追加する場合はここに追加
]

# ==========================================
# 環境変数から認証情報を取得
# ==========================================
LWA_CLIENT_ID = os.environ["LWA_CLIENT_ID"]
LWA_CLIENT_SECRET = os.environ["LWA_CLIENT_SECRET"]
LWA_REFRESH_TOKEN = os.environ["LWA_REFRESH_TOKEN"]
SELLER_ID = os.environ["SELLER_ID"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

MARKETPLACE_ID = "ATVPDKIKX0DER"  # Amazon US

# ==========================================
# アクセストークンの取得
# ==========================================
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

# ==========================================
# 日付の設定（US太平洋時間基準）
# ==========================================
def get_us_dates():
    pt = pytz.timezone("America/Los_Angeles")
    now_pt = datetime.now(pt)
    today_pt = now_pt.date()
    yesterday_pt = today_pt - timedelta(days=1)
    first_day_of_month = today_pt.replace(day=1)
    return yesterday_pt, first_day_of_month, today_pt

# ==========================================
# 注文データの取得
# ==========================================
def get_orders(access_token, created_after, created_before):
    url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders"
    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json",
    }
    params = {
        "MarketplaceIds": MARKETPLACE_ID,
        "CreatedAfter": created_after.isoformat() + "T00:00:00Z",
        "CreatedBefore": created_before.isoformat() + "T00:00:00Z",
        "OrderStatuses": "Shipped,Unshipped,PartiallyShipped",
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json().get("payload", {}).get("Orders", [])

# ==========================================
# 注文データをASINごとに集計
# ==========================================
def aggregate_orders(orders, access_token, target_asins):
    results = {asin: {"order_count": 0, "sales": 0.0, "cancel_count": 0} for asin in target_asins}

    for order in orders:
        order_id = order.get("AmazonOrderId")
        status = order.get("OrderStatus", "")

        # 注文アイテムの取得
        url = f"https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{order_id}/orderItems"
        headers = {"x-amz-access-token": access_token}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            continue
        items = response.json().get("payload", {}).get("OrderItems", [])

        for item in items:
            asin = item.get("ASIN")
            if asin not in results:
                continue
            quantity = int(item.get("QuantityOrdered", 0))
            price = float(item.get("ItemPrice", {}).get("Amount", 0))

            if status in ["Canceled"]:
                results[asin]["cancel_count"] += quantity
            else:
                results[asin]["order_count"] += quantity
                results[asin]["sales"] += price

    return results

# ==========================================
# 在庫データの取得
# ==========================================
def get_inventory(access_token, asin):
    url = "https://sellingpartnerapi-na.amazon.com/fba/inventory/v1/summaries"
    headers = {"x-amz-access-token": access_token}
    params = {
        "details": "true",
        "granularityType": "Marketplace",
        "granularityId": MARKETPLACE_ID,
        "marketplaceIds": MARKETPLACE_ID,
        "sellerSkus": asin,
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return 0
    summaries = response.json().get("payload", {}).get("inventorySummaries", [])
    if summaries:
        return summaries[0].get("totalQuantity", 0)
    return 0

# ==========================================
# 商品名の取得
# ==========================================
def get_product_name(access_token, asin):
    url = f"https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items/{asin}"
    headers = {"x-amz-access-token": access_token}
    params = {
        "marketplaceIds": MARKETPLACE_ID,
        "includedData": "summaries",
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return asin
    summaries = response.json().get("summaries", [])
    if summaries:
        return summaries[0].get("itemName", asin)
    return asin

# ==========================================
# Slackに通知を送信
# ==========================================
def send_slack_notification(message):
    payload = {"text": message}
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    response.raise_for_status()
    print("Slack通知を送信しました")

# ==========================================
# メイン処理
# ==========================================
def main():
    print("処理を開始します...")
    access_token = get_access_token()
    yesterday_pt, first_day_of_month, today_pt = get_us_dates()

    # 昨日の注文データ
    daily_orders = get_orders(access_token, yesterday_pt, today_pt)
    daily_results = aggregate_orders(daily_orders, access_token, ASINS)

    # 当月累計の注文データ
    monthly_orders = get_orders(access_token, first_day_of_month, today_pt)
    monthly_results = aggregate_orders(monthly_orders, access_token, ASINS)

    # Slackメッセージの作成
    message = f"📊 Amazon US 販売レポート\n"
    message += f"━━━━━━━━━━━━━━━\n"
    message += f"📅 {yesterday_pt.strftime('%Y年%m月%d日')}（US時間）\n"
    message += f"━━━━━━━━━━━━━━━\n"

    for asin in ASINS:
        product_name = get_product_name(access_token, asin)
        daily = daily_results[asin]
        monthly = monthly_results[asin]
        inventory = get_inventory(access_token, asin)

        message += f"\n【{asin}】{product_name}\n\n"
        message += f"【本日の実績】\n"
        message += f"注文数：{daily['order_count']}件\n"
        message += f"売上金額：${daily['sales']:,.2f}\n"
        message += f"返品・キャンセル：{daily['cancel_count']}件\n"
        message += f"在庫数：{inventory}個\n\n"
        message += f"【当月累計】\n"
        message += f"注文数：{monthly['order_count']}件\n"
        message += f"売上金額：${monthly['sales']:,.2f}\n"
        message += f"━━━━━━━━━━━━━━━\n"

    send_slack_notification(message)
    print("完了しました")

if __name__ == "__main__":
    main()
