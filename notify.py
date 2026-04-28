import os
import requests
from datetime import datetime, timedelta
import pytz
import time

# ==========================================
# 設定：ASIN・SKUリスト（追加する場合はここに追加）
# ==========================================
PRODUCTS = [
    {
        "asin": "B0GKG32M22",
        "sku": "SH-TTDagashi30-Minibox-v2",
        "name": "TokyoTreat Japanese Snack Box",  # APIで取得失敗時のフォールバック用
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
# Sales and Traffic APIでレポートを作成・取得
# ==========================================
def request_sales_report(access_token, start_date, end_date, asin):
    """レポートをリクエストしてレポートIDを返す"""
    url = "https://sellingpartnerapi-na.amazon.com/reports/2021-06-30/reports"
    headers = {
        "x-amz-access-token": access_token,
        "Content-Type": "application/json",
    }
    payload = {
        "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
        "marketplaceIds": [MARKETPLACE_ID],
        "dataStartTime": start_date.strftime("%Y-%m-%dT00:00:00Z"),
        "dataEndTime": end_date.strftime("%Y-%m-%dT23:59:59Z"),
        "reportOptions": {
            "dateGranularity": "DAY",
            "asinGranularity": "CHILD",
        },
    }
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json().get("reportId")

def wait_for_report(access_token, report_id, max_wait=300):
    """レポートが完成するまで待機"""
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

def get_report_document(access_token, document_id):
    """レポートドキュメントのURLを取得してデータを返す"""
    url = f"https://sellingpartnerapi-na.amazon.com/reports/2021-06-30/documents/{document_id}"
    headers = {"x-amz-access-token": access_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    doc_url = response.json().get("url")

    # レポートデータをダウンロード
    doc_response = requests.get(doc_url)
    doc_response.raise_for_status()
    return doc_response.json()

def get_sales_data(access_token, start_date, end_date, asin):
    """指定期間・ASINの販売ユニット数と売上を取得"""
    print(f"レポートをリクエスト中: {start_date} 〜 {end_date}")
    report_id = request_sales_report(access_token, start_date, end_date, asin)
    if not report_id:
        return {"units": 0, "sales": 0.0, "returns": 0}

    document_id = wait_for_report(access_token, report_id)
    if not document_id:
        return {"units": 0, "sales": 0.0, "returns": 0}

    data = get_report_document(access_token, document_id)

    # ASINに該当するデータを集計
    total_units = 0
    total_sales = 0.0
    total_returns = 0

    sales_by_asin = data.get("salesAndTrafficByAsin", [])
    for item in sales_by_asin:
        if item.get("parentAsin") == asin or item.get("childAsin") == asin:
            summary = item.get("salesByAsin", {})
            total_units += summary.get("unitsOrdered", 0)
            total_sales += float(summary.get("orderedProductSales", {}).get("amount", 0))
            total_returns += summary.get("unitsRefunded", 0)

    return {
        "units": total_units,
        "sales": total_sales,
        "returns": total_returns,
    }

# ==========================================
# FBA在庫データの取得
# ==========================================
def get_inventory(access_token, sku):
    url = "https://sellingpartnerapi-na.amazon.com/fba/inventory/v1/summaries"
    headers = {"x-amz-access-token": access_token}
    params = {
        "details": "true",
        "granularityType": "Marketplace",
        "granularityId": MARKETPLACE_ID,
        "marketplaceIds": MARKETPLACE_ID,
        "sellerSkus": sku,
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"在庫取得エラー: {response.status_code} {response.text}")
        return "取得失敗"

    summaries = response.json().get("payload", {}).get("inventorySummaries", [])
    if summaries:
        return summaries[0].get("inventoryDetails", {}).get("fulfillableQuantity", 0)
    return 0

# ==========================================
# 商品名の取得
# ==========================================
def get_product_name(access_token, asin, fallback_name):
    url = f"https://sellingpartnerapi-na.amazon.com/catalog/2022-04-01/items/{asin}"
    headers = {"x-amz-access-token": access_token}
    params = {
        "marketplaceIds": MARKETPLACE_ID,
        "includedData": "summaries",
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return fallback_name

    summaries = response.json().get("summaries", [])
    if summaries:
        return summaries[0].get("itemName", fallback_name)
    return fallback_name

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

    # Slackメッセージの作成
    message = "📊 Amazon US 販売レポート\n"
    message += "━━━━━━━━━━━━━━━\n"
    message += f"📅 {yesterday_pt.strftime('%Y年%m月%d日')}（US時間）\n"
    message += "━━━━━━━━━━━━━━━\n"

    for product in PRODUCTS:
        asin = product["asin"]
        sku = product["sku"]
        fallback_name = product["name"]

        print(f"処理中: {asin}")

        # 商品名の取得
        product_name = get_product_name(access_token, asin, fallback_name)

        # 昨日の販売データ
        daily = get_sales_data(access_token, yesterday_pt, yesterday_pt, asin)

        # 当月累計の販売データ
        monthly = get_sales_data(access_token, first_day_of_month, yesterday_pt, asin)

        # 在庫数の取得
        inventory = get_inventory(access_token, sku)

        message += f"\n【{asin}】\n"
        message += f"{product_name}\n\n"
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
