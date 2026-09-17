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
    """salesテーブルから最新日付のデータを割引率の高い順に最大MAX_ROWS件取得する。"""
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{SALES_TABLE}"

    query = f"""
        SELECT game_title, store_name, regular_price, sale_price, discount_pct, fetched_at
        FROM `{table_ref}`
        WHERE DATE(fetched_at) = (SELECT MAX(DATE(fetched_at)) FROM `{table_ref}`)
        ORDER BY discount_pct DESC
        LIMIT {MAX_ROWS}
    """
    rows = list(client.query(query).result())

    if not rows:
        return [], None

    latest_date = rows[0]["fetched_at"].date()
    sales = [
        {
            "game_title": row["game_title"],
            "store_name": row["store_name"],
            "regular_price": row["regular_price"],
            "sale_price": row["sale_price"],
            "discount_pct": row["discount_pct"],
        }
        for row in rows
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
