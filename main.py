"""FastAPI Webアプリ: BigQueryのsalesテーブルから最新日のセール情報を一覧表示する。"""

import os
from datetime import date, datetime

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from google.cloud import bigquery

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET = os.getenv("BIGQUERY_DATASET")
SALES_TABLE = "sales"
STEAM_STATS_TABLE = "steam_stats"
PAGE_SIZE = 20
DEFAULT_SORT = "popular"
# 同値のときの並びを安定させるため、第2キーに割引率とgame_idを付ける
SORT_ORDERS = {
    "popular": "COALESCE(st.review_count, 0) DESC, s.discount_pct DESC, s.game_id",
    "discount": "s.discount_pct DESC, s.game_id",
    "new": "s.fetched_at DESC, s.discount_pct DESC, s.game_id",
}
DEFAULT_TYPE = "game"
TYPE_FILTERS = {
    "game": "ゲーム本編",
    "dlc": "DLC",
    "soundtrack": "サウンドトラック",
    "all": "すべて",
}

app = FastAPI()
templates = Jinja2Templates(directory="templates")


def fetch_latest_sales(
    game_type: str = DEFAULT_TYPE, page: int = 1, sort: str = DEFAULT_SORT
) -> tuple[list[dict], date | None, int, int]:
    """salesテーブルから最新日付のデータをgame_idで重複排除し、sortの順に取得する。

    同じgame_idが複数ストアにある場合はdiscount_pctが最大の1件のみ返す。
    game_type が "all" 以外の場合は種別で絞り込む。
    steam_statsの最新レコードをLEFT JOINし、sort="popular"ではレビュー数の多い順に並べる。
    1ページPAGE_SIZE件で、(sales, latest_date, 実際のページ番号, 総ページ数) を返す。
    範囲外のページが指定された場合は最終ページに丸める。
    """
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{SALES_TABLE}"

    type_filter = "" if game_type == "all" else "AND s.game_type = @game_type"
    steam_table_ref = f"{PROJECT_ID}.{DATASET}.{STEAM_STATS_TABLE}"
    order_by = SORT_ORDERS.get(sort, SORT_ORDERS[DEFAULT_SORT])
    query = f"""
        WITH ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY discount_pct DESC) AS rn
            FROM `{table_ref}`
            WHERE DATE(fetched_at) = (SELECT MAX(DATE(fetched_at)) FROM `{table_ref}`)
              AND game_id IS NOT NULL
        )
        SELECT s.game_id, s.game_title, s.store_name, s.regular_price, s.sale_price,
               s.discount_pct, s.game_type, s.image_url, s.store_url, s.fetched_at,
               COUNT(*) OVER () AS total_count
        FROM ranked AS s
        LEFT JOIN (
            SELECT game_id, review_count, player_count, review_score
            FROM `{steam_table_ref}`
            WHERE fetched_at = (SELECT MAX(fetched_at) FROM `{steam_table_ref}`)
        ) AS st
          ON s.game_id = st.game_id
        WHERE s.rn = 1
          {type_filter}
        ORDER BY {order_by}
        LIMIT {PAGE_SIZE}
        OFFSET @offset
    """
    query_parameters = [
        bigquery.ScalarQueryParameter("offset", "INT64", (page - 1) * PAGE_SIZE)
    ]
    if game_type != "all":
        query_parameters.append(
            bigquery.ScalarQueryParameter("game_type", "STRING", game_type)
        )
    job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
    rows = list(client.query(query, job_config=job_config).result())

    if not rows:
        if page > 1:
            # 範囲外のページ: 総件数が分からないので1ページ目から取り直して最終ページに丸める
            first = fetch_latest_sales(game_type, 1, sort)
            total_pages = first[3]
            return fetch_latest_sales(game_type, total_pages, sort) if total_pages > 1 else first
        return [], None, 1, 1

    total_pages = max(1, -(-rows[0]["total_count"] // PAGE_SIZE))

    latest_date = rows[0]["fetched_at"].date()
    sales = [
        {
            "game_id": row["game_id"],
            "game_title": row["game_title"],
            "store_name": row["store_name"],
            "regular_price": row["regular_price"],
            "sale_price": row["sale_price"],
            "discount_pct": row["discount_pct"],
            "game_type": row["game_type"],
            "image_url": row["image_url"],
            "store_url": row["store_url"],
        }
        for row in rows
    ]
    return sales, latest_date, page, total_pages


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
def index(
    request: Request,
    type: str = DEFAULT_TYPE,
    page: int = 1,
    sort: str = Query(default=DEFAULT_SORT),
):
    if type not in TYPE_FILTERS:
        type = DEFAULT_TYPE
    if sort not in SORT_ORDERS:
        sort = DEFAULT_SORT
    page = max(1, page)
    sales, latest_date, page, total_pages = fetch_latest_sales(type, page, sort)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sales": sales,
            "latest_date": latest_date,
            "current_type": type,
            "current_sort": sort,
            "page": page,
            "total_pages": total_pages,
            "today": datetime.now().strftime("%Y-%m-%d"),
            "type_filters": TYPE_FILTERS,
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
