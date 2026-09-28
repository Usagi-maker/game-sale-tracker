# fetch_steam_stats.py
"""salesテーブルのゲームのSteamレビュー数・好評率を取得し、steam_statsテーブルに書き込む。

- ITAD UUIDのgame_id: ITAD GET /games/info/v2 の reviews[source=="Steam"] から取得
- steam_{appid}形式のgame_id: Steam APIから直接取得
"""
import os
import sys
import time
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

ITAD_API_KEY = os.environ["ITAD_API_KEY"]
BQ_PROJECT = os.environ.get("GCP_PROJECT_ID", "")
DATASET = "game_sale_tracker"
SALES_TABLE = f"{BQ_PROJECT}.{DATASET}.sales"
STATS_TABLE = f"{BQ_PROJECT}.{DATASET}.steam_stats"

ITAD_INFO_URL = "https://api.isthereanydeal.com/games/info/v2"


def get_game_ids_from_sales(bq_client) -> list[str]:
    """salesテーブルから直近2日分のgame_idを取得"""
    query = f"""
    SELECT DISTINCT game_id
    FROM `{SALES_TABLE}`
    WHERE fetched_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 DAY)
      AND game_id IS NOT NULL
    """
    result = bq_client.query(query).result()
    return [row.game_id for row in result]


def fetch_itad_reviews(game_id: str) -> dict | None:
    """ITAD games/info/v2 から Steam のレビュー数・好評率を取得する。なければNone。"""
    for _ in range(3):
        try:
            resp = httpx.get(
                ITAD_INFO_URL,
                headers={"ITAD-API-Key": ITAD_API_KEY},
                params={"id": game_id},
                timeout=30,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 35)) + 1
                print(f"  429 レート制限: {wait}秒待機します ({game_id})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            for review in resp.json().get("reviews") or []:
                if review.get("source") == "Steam":
                    return {
                        "review_count": review.get("count"),
                        "review_score": review.get("score"),
                    }
            return None
        except Exception as e:
            print(f"ITAD games/info error for {game_id}: {e}")
            return None
    print(f"ITAD games/info: 429が続いたためスキップ ({game_id})")
    return None


def fetch_steam_reviews(appid: str) -> dict | None:
    """Steam APIからレビュー数・好評率を取得する（steam_形式のgame_id用）。"""
    try:
        resp = httpx.get(
            f"https://store.steampowered.com/appreviews/{appid}",
            params={"json": 1, "language": "all", "purchase_type": "all", "num_per_page": 0},
            timeout=15,
        )
        resp.raise_for_status()
        summary = resp.json().get("query_summary", {})
        total = summary.get("total_reviews", 0)
        if total <= 0:
            return None
        return {
            "review_count": total,
            # ITADのscoreと揃えて好評率(%)を保存する
            "review_score": round(summary.get("total_positive", 0) / total * 100),
        }
    except Exception as e:
        print(f"Steam API error for appid {appid}: {e}")
        return None


def fetch_stats(game_id: str) -> tuple[str, dict | None]:
    if game_id.startswith("steam_"):
        appid = game_id.removeprefix("steam_")
        stats = fetch_steam_reviews(appid) if appid.isdigit() else None
        time.sleep(0.3)  # Steamのレート制限対策
    else:
        stats = fetch_itad_reviews(game_id)
    return game_id, stats


def run_test(game_ids: list[str], limit: int) -> None:
    """先頭limit件だけ逐次取得し、所要時間と結果を表示する（BigQueryには書き込まない）。"""
    for game_id in game_ids[:limit]:
        start = time.perf_counter()
        _, stats = fetch_stats(game_id)
        print(f"  {game_id}: {time.perf_counter() - start:.2f}秒 -> {stats}")


def main():
    bq_client = bigquery.Client(project=BQ_PROJECT)

    print("salesテーブルからgame_idを取得中...")
    game_ids = get_game_ids_from_sales(bq_client)
    print(f"  対象: {len(game_ids)}件")

    # テストモード: python fetch_steam_stats.py --test [件数]
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        limit = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 5
        run_test(game_ids, limit)
        return

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    print("レビュー情報を取得中...")
    for i, game_id in enumerate(game_ids, 1):
        _, stats = fetch_stats(game_id)
        if i % 50 == 0:
            print(f"  {i}/{len(game_ids)}件処理")
        if stats is None:
            continue  # Steamのレビューがないゲームは書き込まない
        rows.append(
            {
                "game_id": game_id,
                "review_count": stats["review_count"],
                "review_score": stats["review_score"],
                "player_count": None,
                "fetched_at": now,
            }
        )
    print(f"  レビュー取得: {len(rows)}件 / {len(game_ids)}件")

    if rows:
        errors = bq_client.insert_rows_json(STATS_TABLE, rows)
        if errors:
            print(f"BigQuery書き込みエラー: {errors}")
        else:
            print(f"✓ {len(rows)}件書き込み完了")
    else:
        print("書き込むデータがありません")


if __name__ == "__main__":
    main()
