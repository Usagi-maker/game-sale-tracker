"""FastAPI Webアプリ: BigQueryのsalesテーブルから最新日のセール情報を一覧表示する。"""

import os
from datetime import date

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from google.cloud import bigquery

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET = os.getenv("BIGQUERY_DATASET")
SALES_TABLE = "sales"
MAX_ROWS = 50

app = FastAPI()
templates = Jinja2Templates(directory="templates")


def fetch_latest_sales() -> tuple[list[dict], date | None]:
    """salesテーブルから最新日付のデータを割引率の高い順に取得する。

    サービスアカウントにbigquery.jobs.create権限がないため、SQLクエリではなく
    tabledata.list (list_rows) で全件取得し、Python側で最新日抽出・ソートを行う。
    """
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{SALES_TABLE}"
    rows = list(client.list_rows(table_ref))

    if not rows:
        return [], None

    latest_date = max(row["fetched_at"].date() for row in rows)
    latest_rows = [row for row in rows if row["fetched_at"].date() == latest_date]
    latest_rows.sort(key=lambda row: row["discount_pct"] or 0, reverse=True)

    sales = [
        {
            "game_title": row["game_title"],
            "store_name": row["store_name"],
            "regular_price": row["regular_price"],
            "sale_price": row["sale_price"],
            "discount_pct": row["discount_pct"],
        }
        for row in latest_rows[:MAX_ROWS]
    ]
    return sales, latest_date


@app.get("/")
def index(request: Request):
    sales, latest_date = fetch_latest_sales()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sales": sales,
            "latest_date": latest_date,
        },
    )
