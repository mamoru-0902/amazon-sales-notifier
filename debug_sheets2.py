import os
import json
from datetime import datetime, timedelta
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests

SPREADSHEET_ID = "1jHV2OZfsclDfC4Irl5S0FNwxZELzsuiz3edKp2SIb94"
SHEET_TAB_NAME = "Order数と配送計画_v2"
DATE_COLUMN = "D"
GOOGLE_SHEETS_CREDENTIALS = os.environ["GOOGLE_SHEETS_CREDENTIALS"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

def get_sheets_service():
    credentials_info = json.loads(GOOGLE_SHEETS_CREDENTIALS)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=credentials)

def send_slack(message):
    requests.post(SLACK_WEBHOOK_URL, json={"text": message})

def main():
    pt = pytz.timezone("America/Los_Angeles")
    now_pt = datetime.now(pt)
    yesterday_pt = (now_pt - timedelta(days=1)).date()

    print(f"検索対象日: {yesterday_pt}")

    service = get_sheets_service()

    # D列の値を全て取得
    range_name = f"{SHEET_TAB_NAME}!{DATE_COLUMN}:{DATE_COLUMN}"
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name,
    ).execute()

    values = result.get("values", [])

    # 検索フォーマット
    formats = [
        yesterday_pt.strftime("%m/%d"),
        yesterday_pt.strftime("%-m/%-d"),
        yesterday_pt.strftime("%Y/%m/%d"),
        yesterday_pt.strftime("%-m/%-d/%Y"),
        yesterday_pt.strftime("%m/%d/%Y"),
    ]

    msg = f"🔍 Sheetsデバッグ結果\n"
    msg += f"検索対象日: {yesterday_pt}\n"
    msg += f"検索フォーマット: {formats}\n\n"

    # 行マッチングテスト
    matched_row = None
    for i, row in enumerate(values):
        if row and row[0].strip() in formats:
            matched_row = i + 1
            msg += f"✅ マッチした行: {matched_row} (値: '{row[0]}')\n"
            break

    if not matched_row:
        msg += "❌ マッチする行が見つかりませんでした\n\n"
        # 428行目付近の値を確認
        msg += "【428行目付近の値（repr形式）】\n"
        for i in range(425, 430):
            if i < len(values):
                row = values[i]
                val = row[0] if row else "(空)"
                msg += f"行{i+1}: '{val}' → repr: {repr(val)}\n"
    else:
        # 書き込みテスト
        msg += f"\n書き込みテスト実行中...\n"
        test_range = f"{SHEET_TAB_NAME}!F{matched_row}"
        body = {"values": [[999]]}
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=test_range,
            valueInputOption="RAW",
            body=body,
        ).execute()
        msg += f"✅ F{matched_row}に999を書き込みました。スプレッドシートを確認してください。\n"

    print(msg)
    send_slack(msg)

if __name__ == "__main__":
    main()
