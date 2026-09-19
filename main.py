"""FastAPI Webアプリ: BigQueryのsalesテーブルから最新日のセール情報を一覧表示する。"""

import os
from datetime import date

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
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
        SELECT game_id, game_title, store_name, regular_price, sale_price, discount_pct, fetched_at
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
            "game_id": row["game_id"],
            "game_title": row["game_title"],
            "store_name": row["store_name"],
            "regular_price": row["regular_price"],
            "sale_price": row["sale_price"],
            "discount_pct": row["discount_pct"],
        }
        for row in rows
    ]
    return sales, latest_date


def fetch_game_history(game_id: str) -> list[dict]:
    """指定game_idの全セール履歴を新しい順に取得する。"""
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{SALES_TABLE}"

    query = f"""
        SELECT game_title, store_name, regular_price, sale_price, discount_pct, DATE(fetched_at) as date
        FROM `{table_ref}`
        WHERE game_id = @game_id
        ORDER BY fetched_at DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("game_id", "STRING", game_id)]
    )
    rows = list(client.query(query, job_config=job_config).result())

    return [
        {
            "game_title": row["game_title"],
            "store_name": row["store_name"],
            "regular_price": row["regular_price"],
            "sale_price": row["sale_price"],
            "discount_pct": row["discount_pct"],
            "date": row["date"],
        }
        for row in rows
    ]


def fetch_store_stats() -> list[dict]:
    """salesテーブルからストアごとの集計を取得する。"""
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{SALES_TABLE}"

    query = f"""
        SELECT store_name,
          COUNT(DISTINCT DATE(fetched_at)) as days_tracked,
          COUNT(*) as total_deals,
          ROUND(AVG(discount_pct), 1) as avg_discount,
          ROUND(MAX(discount_pct), 1) as max_discount
        FROM `{table_ref}`
        GROUP BY store_name
        ORDER BY avg_discount DESC
    """
    rows = list(client.query(query).result())

    return [
        {
            "store_name": row["store_name"],
            "days_tracked": row["days_tracked"],
            "total_deals": row["total_deals"],
            "avg_discount": row["avg_discount"],
            "max_discount": row["max_discount"],
        }
        for row in rows
    ]


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


@app.get("/games/{game_id}")
def game_detail(request: Request, game_id: str):
    history = fetch_game_history(game_id)
    if not history:
        raise HTTPException(status_code=404, detail="ゲームが見つかりませんでした。")

    return templates.TemplateResponse(
        request,
        "game_detail.html",
        {
            "game_id": game_id,
            "game_title": history[0]["game_title"],
            "history": history,
        },
    )


@app.get("/stores")
def stores(request: Request):
    store_stats = fetch_store_stats()
    return templates.TemplateResponse(
        request,
        "stores.html",
        {
            "store_stats": store_stats,
        },
    )
