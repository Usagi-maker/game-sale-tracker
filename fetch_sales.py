"""IsThereAnyDeal API からセール中のゲーム情報を取得し、CSVに出力するスクリプト。"""

import csv
import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from google.cloud import bigquery

DEALS_URL = "https://api.isthereanydeal.com/deals/v2"
MAX_DEALS = 20
OUTPUT_DIR = "output"


def fetch_deals(api_key: str) -> list[dict]:
    response = httpx.get(
        DEALS_URL,
        headers={"ITAD-API-Key": api_key},
        params={
            "country": "US",
            "limit": MAX_DEALS,
        },
    )
    response.raise_for_status()
    return response.json().get("list", [])


def build_rows(deals: list[dict], fetched_at: str) -> list[dict]:
    rows = []
    for item in deals:
        deal = item.get("deal", {})
        rows.append(
            {
                "title": item.get("title", ""),
                "shop": deal.get("shop", {}).get("name", ""),
                "regular_price": deal.get("regular", {}).get("amount"),
                "sale_price": deal.get("price", {}).get("amount"),
                "cut": deal.get("cut"),
                "fetched_at": fetched_at,
            }
        )
    return rows


def write_csv(rows: list[dict]) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = os.path.join(OUTPUT_DIR, f"sales_{datetime.now():%Y%m%d}.csv")

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["ゲーム名", "ストア名", "通常価格", "セール価格", "割引率(%)", "取得日時"]
        )
        for row in rows:
            writer.writerow(
                [
                    row["title"],
                    row["shop"],
                    row["regular_price"],
                    row["sale_price"],
                    row["cut"],
                    row["fetched_at"],
                ]
            )

    return filename


def write_bigquery(rows: list[dict], project_id: str, dataset: str, table: str) -> int:
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset}.{table}"

    bq_rows = [
        {
            "game_title": row["title"],
            "store_name": row["shop"],
            "regular_price": row["regular_price"],
            "sale_price": row["sale_price"],
            "discount_pct": row["cut"],
            "fetched_at": row["fetched_at"],
        }
        for row in rows
    ]

    errors = client.insert_rows_json(table_ref, bq_rows)
    if errors:
        raise RuntimeError(f"BigQueryへの書き込みに失敗しました: {errors}")

    return len(bq_rows)


def main() -> None:
    load_dotenv()
    api_key = os.getenv("ITAD_API_KEY")
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BIGQUERY_DATASET")
    table = os.getenv("BIGQUERY_TABLE")

    if not api_key:
        print(".envに ITAD_API_KEY を設定してください。", file=sys.stderr)
        sys.exit(1)

    if not project_id or not dataset or not table:
        print(
            ".envに GCP_PROJECT_ID, BIGQUERY_DATASET, BIGQUERY_TABLE を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    deals = fetch_deals(api_key)
    fetched_at = datetime.now().isoformat()
    rows = build_rows(deals, fetched_at)

    filename = write_csv(rows)
    print(f"{len(rows)}件のセール情報を {filename} に保存しました。")

    bq_count = write_bigquery(rows, project_id, dataset, table)
    print(f"BigQueryに{bq_count}件書き込みました。")


if __name__ == "__main__":
    main()
