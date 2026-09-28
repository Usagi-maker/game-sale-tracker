"""Steam公式APIから注目セール・トップセラーの割引ゲームを取得し、BigQueryのsalesテーブルに書き込むスクリプト。"""

import os
import sys
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from google.cloud import bigquery

FEATURED_URL = "https://store.steampowered.com/api/featuredcategories/?cc=jp&l=japanese"
STORE_APP_URL = "https://store.steampowered.com/app/{appid}/"
SECTIONS = ("specials", "top_sellers")


def fetch_featured_items() -> dict[int, dict]:
    """specialsとtop_sellersのアイテムをappidをキーに統合して返す（重複は1件に集約）。"""
    response = httpx.get(FEATURED_URL, timeout=30)
    response.raise_for_status()
    data = response.json()

    items: dict[int, dict] = {}
    for section in SECTIONS:
        for item in (data.get(section) or {}).get("items", []):
            appid = item.get("id")
            if appid is not None:
                items.setdefault(appid, item)
    return items


def build_rows(items: dict[int, dict], fetched_at: str) -> list[dict]:
    rows = []
    for appid, item in items.items():
        original_price = item.get("original_price")
        final_price = item.get("final_price")
        discount_pct = item.get("discount_percent") or 0

        if not item.get("discounted") or discount_pct == 0:
            continue
        if not original_price or final_price is None:
            continue

        rows.append(
            {
                "game_id": f"steam_{appid}",
                "game_title": item.get("name", ""),
                "store_name": "Steam",
                "regular_price": original_price / 100,
                "sale_price": final_price / 100,
                "discount_pct": discount_pct,
                "fetched_at": fetched_at,
                "game_type": "game",
                "image_url": item.get("header_image") or None,
                "store_url": STORE_APP_URL.format(appid=appid),
            }
        )
    return rows


def write_bigquery(rows: list[dict], project_id: str, dataset: str, table: str) -> int:
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset}.{table}"

    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"BigQueryへの書き込みに失敗しました: {errors}")

    return len(rows)


def main() -> None:
    load_dotenv()
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BIGQUERY_DATASET")
    table = os.getenv("BIGQUERY_TABLE")

    if not project_id or not dataset or not table:
        print(
            ".envに GCP_PROJECT_ID, BIGQUERY_DATASET, BIGQUERY_TABLE を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    items = fetch_featured_items()
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = build_rows(items, fetched_at)

    if rows:
        write_bigquery(rows, project_id, dataset, table)
    print(f"Steam注目セール: {len(rows)}件をBigQueryに書き込みました")


if __name__ == "__main__":
    main()
