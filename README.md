# Game Sale Tracker

[![Fetch Sales](https://github.com/Usagi-maker/game-sale-tracker/actions/workflows/fetch_sales.yml/badge.svg)](https://github.com/Usagi-maker/game-sale-tracker/actions/workflows/fetch_sales.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)

A data pipeline that automatically collects daily game sale data from digital
game stores (Steam, GOG, Fanatical, etc.), enriches it with Steam player
counts and review scores, stores everything in Google BigQuery, and
visualizes it in Looker Studio.

## Overview

Every day, this pipeline:

1. Fetches the current top game deals across stores via the
   [IsThereAnyDeal API](https://isthereanydeal.com/), priced in JPY.
2. Fetches player counts and review scores for the corresponding Steam titles
   via the official Steam Web API.
3. Loads both datasets into BigQuery for long-term storage and analysis.
4. Feeds a Looker Studio dashboard for visualization.

The whole process runs unattended on a daily schedule via GitHub Actions.

## Architecture

```
IsThereAnyDeal API ---> fetch_sales.py       ---> GitHub Actions ---> BigQuery ---> Looker Studio
                                                    (daily cron)         |
Steam Web API       ---> fetch_steam_stats.py --->      ^                |
                                                         |________________|
```

Both scripts are triggered sequentially by a single scheduled GitHub Actions
workflow:

```
GitHub Actions (cron, daily)
  └── fetch_sales.py        → BigQuery: sales table
  └── fetch_steam_stats.py  → BigQuery: steam_stats table
```

## Tech Stack

| Category         | Technology                                   |
| ----------------- | --------------------------------------------- |
| Language           | Python (`httpx`, `google-cloud-bigquery`)     |
| Data warehouse     | Google BigQuery                               |
| Automation / CI    | GitHub Actions                                |
| Visualization      | Looker Studio                                 |
| External data      | IsThereAnyDeal API, Steam Web API             |

## Features

- **Daily automated sale collection** — up to 100 deals per run, priced in JPY.
- **Steam enrichment** — current player count and review score/count for each
  Steam title found in the daily deals.
- **Daily accumulation in BigQuery** — every run appends new rows, building a
  historical dataset over time.
- **Looker Studio dashboard** — visualizes price trends, discount rates, and
  player/review metrics.

## Data Model

### `sales` table

| Column          | Type      | Description                          |
| ---------------- | --------- | ------------------------------------- |
| `game_title`      | STRING    | Name of the game                      |
| `store_name`      | STRING    | Store the deal was found on (e.g. Steam) |
| `regular_price`   | FLOAT     | Regular price (JPY)                   |
| `sale_price`      | FLOAT     | Discounted price (JPY)                |
| `discount_pct`    | INTEGER   | Discount percentage                   |
| `fetched_at`      | TIMESTAMP | Time the record was fetched           |

### `steam_stats` table

| Column          | Type      | Description                             |
| ---------------- | --------- | ----------------------------------------- |
| `steam_app_id`    | INTEGER   | Steam App ID                              |
| `game_title`      | STRING    | Name of the game (Japanese, via Steam)    |
| `player_count`     | INTEGER   | Current concurrent player count           |
| `review_score`     | FLOAT     | Positive review percentage (0-100)        |
| `review_count`     | INTEGER   | Total number of reviews                   |
| `fetched_at`       | TIMESTAMP | Time the record was fetched               |

## Setup

### Prerequisites

- A Google Cloud Platform account with a BigQuery dataset and a service
  account key with permission to write to it
- An [IsThereAnyDeal API key](https://isthereanydeal.com/apps/my/)
- A GitHub account (to run the scheduled workflow)

### Environment variables

Create a `.env` file in the project root (see `.gitignore` — this file is
never committed):

```
ITAD_API_KEY=your_isthereanydeal_api_key
GCP_PROJECT_ID=your_gcp_project_id
BIGQUERY_DATASET=your_bigquery_dataset
BIGQUERY_TABLE=sales
GOOGLE_APPLICATION_CREDENTIALS=gcp-key.json
```

Place your GCP service account key JSON at `gcp-key.json` in the project
root (also gitignored).

### Install dependencies

```
pip install -r requirements.txt
```

### Run locally

```
python fetch_sales.py
python fetch_steam_stats.py
```

### GitHub Actions setup

To run the pipeline automatically on GitHub Actions, add the following
repository secrets (Settings → Secrets and variables → Actions):

| Secret                             | Description                                |
| ----------------------------------- | -------------------------------------------- |
| `ITAD_API_KEY`                       | IsThereAnyDeal API key                       |
| `GCP_PROJECT_ID`                     | GCP project ID                               |
| `BIGQUERY_DATASET`                   | BigQuery dataset name                        |
| `BIGQUERY_TABLE`                     | BigQuery table name for sales (`sales`)      |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | Full contents of the GCP service account key JSON |

The workflow at `.github/workflows/fetch_sales.yml` runs daily at 9:00 JST,
executing `fetch_sales.py` followed by `fetch_steam_stats.py`.

## Credits

- Data provided by [IsThereAnyDeal API](https://isthereanydeal.com/)
- Game data from [Steam](https://store.steampowered.com/)
