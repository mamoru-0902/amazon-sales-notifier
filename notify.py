import os
import requests
from datetime import datetime, timedelta
import pytz
import time
import csv
import io

# ==========================================
# 設定：ASIN・SKUリスト（追加する場合はここに追加）
# ==========================================
PRODUCTS = [
    {
        "asin": "B0GKG32M22",
        "sku": "SH-TTDagashi30-Minibox-v2",
        "name": "TokyoTreat Japanese Snack Box",
    },
    # 新しい商品を追加する場合は以下のように追加：
    # {
    #     "asin": "B0XXXXXXXXX",
    #     "sku": "YOUR-SKU-HERE",
    #     "name": "商品名",
    # },
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
# 注文レポートをリクエスト・取得
# ==========================================
def request_order_report(access_token, start_date, end_date):
    url = "https://sellingpartnerapi-na.amazon.com/reports/2021-06-30/reports"
    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json",
    }
    payload = {
        "reportType": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
        "marketplaceIds": [MARKETPLACE_ID],
        "dataStartTime": start_date.strftime("%Y-%m-%dT00:00:00Z"),
        "dataEndTime": end_date.strftime("%Y-%m-%dT23:59:59Z"),
    }
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json().get("reportId")

def wait_for_report(access_token, report_id, max_wait=300):
    url = f"https://sellingpartnerapi-na.amazon.com/reports/2021-06-30/reports/{report_id}"
    headers = {"x-amz-access-token": access_token}

    for _ in range(max_wait // 10):
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        status = data.get("processingStatus")
        print(f"レポートステータス: {status}")

        if status == "DONE":
            return data.get("reportDocumentId")
        elif status in ["CANCELLED", "FATAL"]:
            print(f"レポート失敗: {status}")
            return None

        time.sleep(10)

    print("レポートのタイムアウト")
    return None

def get_report_document_csv(access_token, document_id):
    url = f"https://sellingpartnerapi-na.amazon.com/reports/2021-06-30/documents/{document_id}"
    headers = {"x-amz-access-token": access_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    doc_url = response.json().get("url")

    doc_response = requests.get(doc_url)
    doc_response.raise_for_status()
    return doc_response.text

# ==========================================
# CSVデータをASINごとに集計
# ==========================================
def aggregate_csv_data(csv_text, target_asins):
    results = {asin: {"units": 0, "sales": 0.0, "returns": 0} for asin in target_asins}

    reader = csv.DictReader(io.StringIO(csv_text), delimiter="\t")
    for row in reader:
        asin = row.get("asin", "")
        if asin not in results:
            continue

        status = row.get("order-status", "")
        if status == "Cancelled":
            continue

        try:
            quantity = int(row.get("quantity", 0))
            price = float(row.get("item-price", 0))
        except (ValueError, TypeError):
            quantity = 0
            price = 0.0

        results[asin]["units"] += quantity
        results[asin]["sales"] += price

    return results

# ==========================================
# FBA在庫レポートで在庫数を取得
# ==========================================
def get_inventory(access_token, sku):
    url = "https://sellingpartnerapi-na.amazon.com/reports/2021-06-30/reports"
    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json",
    }
    payload = {
        "reportType": "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA",
        "marketplaceIds": [MARKETPLACE_ID],
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"在庫レポートリクエスト失敗: {response.status_code} {response.text}")
        return "取得失敗"

    report_id = response.json().get("reportId")
    document_id = wait_for_report(access_token, report_id)
    if not document_id:
        return "取得失敗"

    csv_text = get_report_document_csv(access_token, document_id)
    reader = csv.DictReader(io.StringIO(csv_text), delimiter="\t")
    for row in reader:
        if row.get("seller-sku") == sku:
            return int(row.get("afn-fulfillable-quantity", 0))

    print(f"在庫情報が見つかりませんでした: {sku}")
    return "取得失敗"

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

    print(f"対象日（昨日）: {yesterday_pt}")
    print(f"当月開始日: {first_day_of_month}")

    asins = [p["asin"] for p in PRODUCTS]

    # 昨日の注文レポート取得
    print("昨日の注文レポートをリクエスト中...")
    daily_report_id = request_order_report(access_token, yesterday_pt, yesterday_pt)
    daily_doc_id = wait_for_report(access_token, daily_report_id)
    daily_csv = get_report_document_csv(access_token, daily_doc_id)
    daily_results = aggregate_csv_data(daily_csv, asins)

    # 当月累計の注文レポート取得
    print("当月累計の注文レポートをリクエスト中...")
    monthly_report_id = request_order_report(access_token, first_day_of_month, yesterday_pt)
    monthly_doc_id = wait_for_report(access_token, monthly_report_id)
    monthly_csv = get_report_document_csv(access_token, monthly_doc_id)
    monthly_results = aggregate_csv_data(monthly_csv, asins)

    # Slackメッセージの作成
    message = "📊 Amazon US 販売レポート\n"
    message += "━━━━━━━━━━━━━━━\n"
    message += f"📅 {yesterday_pt.strftime('%Y年%m月%d日')}（US時間）\n"
    message += "━━━━━━━━━━━━━━━\n"

    for product in PRODUCTS:
        asin = product["asin"]
        sku = product["sku"]
        name = product["name"]

        daily = daily_results[asin]
        monthly = monthly_results[asin]
        inventory = get_inventory(access_token, sku)

        message += f"\n【{asin}】\n"
        message += f"{name}\n\n"
        message += "【本日の実績】\n"
        message += f"販売数：{daily['units']}個\n"
        message += f"売上金額：${daily['sales']:,.2f}\n"
        message += f"返品数：{daily['returns']}件\n"
        message += f"在庫数：{inventory}個\n\n"
        message += "【当月累計】\n"
        message += f"販売数：{monthly['units']}個\n"
        message += f"売上金額：${monthly['sales']:,.2f}\n"
        message += "━━━━━━━━━━━━━━━\n"

    send_slack_notification(message)
    print("完了しました")

if __name__ == "__main__":
    main()
