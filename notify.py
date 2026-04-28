import os
import requests
from datetime import datetime, timedelta
import pytz
import time
import csv
import io
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

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
# Google Sheets設定
# ==========================================
SPREADSHEET_ID = "1jHV2OZfsclDfC4Irl5S0FNwxZELzsuiz3edKp2SIb94"
SHEET_TAB_NAME = "Order数と配送計画_v2"
DATE_COLUMN = "D"       # 日付列
SALES_COLUMN = "F"      # 販売数入力列
INVENTORY_COLUMN = "N"  # 在庫予測数列

# ==========================================
# 環境変数から認証情報を取得
# ==========================================
LWA_CLIENT_ID = os.environ["LWA_CLIENT_ID"]
LWA_CLIENT_SECRET = os.environ["LWA_CLIENT_SECRET"]
LWA_REFRESH_TOKEN = os.environ["LWA_REFRESH_TOKEN"]
SELLER_ID = os.environ["SELLER_ID"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
GOOGLE_SHEETS_CREDENTIALS = os.environ["GOOGLE_SHEETS_CREDENTIALS"]

MARKETPLACE_ID = "ATVPDKIKX0DER"  # Amazon US

# ==========================================
# Google Sheets APIクライアントの初期化
# ==========================================
def get_sheets_service():
    credentials_info = json.loads(GOOGLE_SHEETS_CREDENTIALS)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=credentials)

# ==========================================
# スプレッドシートから日付に対応する行を検索
# ==========================================
def find_row_by_date(service, target_date):
    # D列全体を取得して最後にマッチした行を返す（年をまたいでも対応）
    range_name = f"{SHEET_TAB_NAME}!{DATE_COLUMN}:{DATE_COLUMN}"
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name,
    ).execute()

    values = result.get("values", [])
    target_str_formats = [
        target_date.strftime("%m/%d"),      # 例: 04/26
        target_date.strftime("%-m/%-d"),    # 例: 4/26
        target_date.strftime("%Y/%m/%d"),   # 例: 2026/04/26
        target_date.strftime("%-m/%-d/%Y"), # 例: 4/26/2026
        target_date.strftime("%m/%d/%Y"),   # 例: 04/26/2026
    ]

    # 最後にマッチした行を返す（年をまたいでも最新年のデータを使用）
    matched_row = None
    for i, row in enumerate(values):
        if row and row[0].strip() in target_str_formats:
            matched_row = i + 1  # 1始まりの行番号

    if matched_row:
        print(f"マッチした行: {matched_row}")
        return matched_row

    print(f"日付が見つかりませんでした: {target_date}")
    return None

# ==========================================
# スプレッドシートに販売数を書き込む
# ==========================================
def write_sales_to_sheet(service, row_number, sales_units):
    range_name = f"{SHEET_TAB_NAME}!{SALES_COLUMN}{row_number}"
    body = {"values": [[sales_units]]}
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name,
        valueInputOption="RAW",
        body=body,
    ).execute()
    print(f"販売数を書き込みました: 行{row_number} = {sales_units}個")

# ==========================================
# スプレッドシートから在庫予測数を読み取る
# ==========================================
def read_inventory_forecast(service, row_number):
    range_name = f"{SHEET_TAB_NAME}!{INVENTORY_COLUMN}{row_number}"
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name,
    ).execute()
    values = result.get("values", [])
    if values and values[0]:
        try:
            return int(float(values[0][0]))
        except (ValueError, TypeError):
            return "取得失敗"
    return "取得失敗"

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

    # Google Sheetsサービス初期化
    print("Google Sheetsに接続中...")
    sheets_service = get_sheets_service()

    # Slackメッセージの作成
    message = "📊 Amazon US 販売レポート\n"
    message += "━━━━━━━━━━━━━━━\n"
    message += f"📅 {yesterday_pt.strftime('%Y年%m月%d日')}（US時間）\n"
    message += "━━━━━━━━━━━━━━━\n"

    for product in PRODUCTS:
        asin = product["asin"]
        name = product["name"]

        daily = daily_results[asin]
        monthly = monthly_results[asin]

        # スプレッドシートに販売数を書き込む
        row_number = find_row_by_date(sheets_service, yesterday_pt)
        inventory_forecast = "取得失敗"

        if row_number:
            write_sales_to_sheet(sheets_service, row_number, daily["units"])
            # 書き込み後に在庫予測数を読み取る（Sheetsの数式が計算されるまで少し待つ）
            time.sleep(3)
            inventory_forecast = read_inventory_forecast(sheets_service, row_number)
            print(f"在庫予測数: {inventory_forecast}")
        else:
            print("対応する日付の行が見つかりませんでした")

        message += f"\n【{asin}】\n"
        message += f"{name}\n\n"
        message += "【本日の実績】\n"
        message += f"販売数：{daily['units']}個\n"
        message += f"売上金額：${daily['sales']:,.2f}\n"
        message += f"返品数：{daily['returns']}件\n"
        message += f"在庫予測数：{inventory_forecast}個\n\n"
        message += "【当月累計】\n"
        message += f"販売数：{monthly['units']}個\n"
        message += f"売上金額：${monthly['sales']:,.2f}\n"
        message += "━━━━━━━━━━━━━━━\n"

    send_slack_notification(message)
    print("完了しました")

if __name__ == "__main__":
    main()
