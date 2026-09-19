"""Steam APIからプレイヤー数・レビュー情報を取得し、BigQueryのsteam_statsテーブルに書き込むスクリプト。

対象ゲームのSteam App IDは、IsThereAnyDeal API (deals/v2) でSteamのセール情報を取得し、
各ゲームのITAD内部IDを games/info/v2 で引いてappidを特定することで取得する。
"""

import os
import sys
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv
from google.cloud import bigquery

DEALS_URL = "https://api.isthereanydeal.com/deals/v2"
GAME_INFO_URL = "https://api.isthereanydeal.com/games/info/v2"
PLAYER_COUNT_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
APPREVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"

STEAM_SHOP_ID = 61  # IsThereAnyDealにおけるSteamのshop id
MAX_DEALS = 100
REQUEST_INTERVAL_SEC = 1
STEAM_STATS_TABLE = "steam_stats"

HEADERS = {"User-Agent": "Mozilla/5.0 (game-sale-tracker)"}


def fetch_steam_deals(api_key: str) -> list[dict]:
    response = httpx.get(
        DEALS_URL,
        headers={"ITAD-API-Key": api_key},
        params={"shops": STEAM_SHOP_ID, "country": "JP", "limit": MAX_DEALS},
    )
    response.raise_for_status()
    return response.json().get("list", [])


def fetch_steam_appid(itad_id: str, api_key: str) -> tuple[int | None, str | None]:
    """ITADのゲームIDからSteam App IDとタイトルを取得する。取得できない場合は (None, None)。"""
    try:
        response = httpx.get(GAME_INFO_URL, params={"key": api_key, "id": itad_id}, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("appid"), data.get("title")
    except httpx.HTTPError:
        return None, None


def extract_steam_games(deals: list[dict], api_key: str) -> list[dict]:
    """dealsからSteam App ID・ITADゲームID・ゲームタイトルを抽出する（ゲーム本体のみ、重複除去）。"""
    games: dict[int, dict] = {}
    for item in deals:
        if item.get("type") != "game":
            continue

        appid, title = fetch_steam_appid(item["id"], api_key)
        if appid is None or appid in games:
            continue
        games[appid] = {"game_id": item["id"], "title": title or item.get("title", "")}

    return [
        {"appid": appid, "game_id": info["game_id"], "title": info["title"]}
        for appid, info in games.items()
    ]


def fetch_player_count(appid: int) -> int | None:
    try:
        response = httpx.get(PLAYER_COUNT_URL, params={"appid": appid}, timeout=10)
        response.raise_for_status()
        data = response.json().get("response", {})
        if data.get("result") == 1:
            return data.get("player_count")
    except httpx.HTTPError:
        pass
    return None


def fetch_game_title_ja(appid: int, fallback_title: str) -> str:
    """appdetails(l=japanese)からゲーム名を取得する。取得できない場合はfallback_titleを返す。"""
    try:
        response = httpx.get(
            APPDETAILS_URL,
            params={"appids": appid, "l": "japanese"},
            headers=HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        entry = response.json().get(str(appid), {})
        if entry.get("success"):
            return entry.get("data", {}).get("name", fallback_title)
    except httpx.HTTPError:
        pass
    return fallback_title


def fetch_review_stats(appid: int) -> tuple[int | None, int | None]:
    """(review_score, review_count) を返す。

    appdetailsのレスポンスにはrecommendation_percentageに相当する値が含まれないため、
    Steamのappreviewsエンドポイントのquery_summaryからpositive比率を算出する。
    取得できない場合は (None, None)。
    """
    try:
        response = httpx.get(
            APPREVIEWS_URL.format(appid=appid),
            params={"json": 1, "language": "all", "purchase_type": "all"},
            headers=HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        summary = response.json().get("query_summary", {})
        total_positive = summary.get("total_positive")
        total_reviews = summary.get("total_reviews")
        if total_positive is not None and total_reviews:
            review_score = round(total_positive / total_reviews * 100)
        else:
            review_score = None
        return review_score, total_reviews
    except httpx.HTTPError:
        pass
    return None, None


def build_rows(games: list[dict], fetched_at: str) -> list[dict]:
    rows = []
    for game in games:
        appid = game["appid"]

        game_title = fetch_game_title_ja(appid, game["title"])
        time.sleep(REQUEST_INTERVAL_SEC)

        player_count = fetch_player_count(appid)
        time.sleep(REQUEST_INTERVAL_SEC)

        review_score, review_count = fetch_review_stats(appid)
        time.sleep(REQUEST_INTERVAL_SEC)

        rows.append(
            {
                "game_id": game["game_id"],
                "steam_app_id": appid,
                "game_title": game_title,
                "player_count": player_count,
                "review_score": review_score,
                "review_count": review_count,
                "fetched_at": fetched_at,
            }
        )
    return rows


def write_bigquery(rows: list[dict], project_id: str, dataset: str) -> int:
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset}.{STEAM_STATS_TABLE}"

    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"BigQueryへの書き込みに失敗しました: {errors}")

    return len(rows)


def main() -> None:
    load_dotenv()
    api_key = os.getenv("ITAD_API_KEY")
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BIGQUERY_DATASET")

    if not api_key:
        print(".envに ITAD_API_KEY を設定してください。", file=sys.stderr)
        sys.exit(1)

    if not project_id or not dataset:
        print(
            ".envに GCP_PROJECT_ID, BIGQUERY_DATASET を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    deals = fetch_steam_deals(api_key)
    games = extract_steam_games(deals, api_key)

    fetched_at = datetime.now().isoformat()
    rows = build_rows(games, fetched_at)

    bq_count = write_bigquery(rows, project_id, dataset)
    print(f"steam_statsに{bq_count}件書き込みました。")


if __name__ == "__main__":
    main()
