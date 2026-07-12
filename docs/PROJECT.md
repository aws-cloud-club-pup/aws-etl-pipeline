# Project Brief — Serverless ETL on AWS

Welcome! In this workshop you'll build a **complete, event-driven data pipeline**
on AWS — no servers to manage, no infrastructure code, no third-party libraries.
Everything runs on managed AWS services you configure through the Console.

By the end you'll have a pipeline that, **every 15 minutes on its own**, pulls live
Philippine data from public APIs, lands it in a data lake, transforms it, loads it
into a data warehouse, and lets you query and visualize it.

---

## What you're building

A pipeline that moves data through five stages:

```
 EventBridge (every 15 min)
        │  triggers
        ▼
 ┌──────────────┐   HTTPS    Open-Meteo weather
 │  Lambda      │ ────────►  Open-Meteo air quality
 │  etl-scraper │ ────────►  USGS earthquakes (PH)
 └──────┬───────┘
        │ writes 3 raw CSVs
        ▼
 ┌──────────── S3 data lake ────────────┐
 │  raw/…            processed/…         │
 └──────┬─────────────────────▲─────────┘
        │ ObjectCreated (raw/) │ writes processed CSV
        ▼                      │
 ┌──────────────────┐          │
 │  Lambda          │ ─────────┘
 │  etl-transformer │  COPY via Redshift Data API
 └──────┬───────────┘
        ▼
 ┌──────────────────────────────────────┐
 │  Redshift: weather · air_quality ·    │
 │            earthquakes                │
 └──────────────────────────────────────┘
```

**Why "event-driven"?** Nothing runs on a schedule you babysit. A timer event
(EventBridge) kicks off extraction, and each new file *event* in S3 automatically
triggers the transform-and-load. The pipeline reacts to events — that's the core
idea you'll take away.

---

## The stages, and who's presenting each

| # | Stage | What happens | Talk |
|---|-------|--------------|------|
| 1 | **Setup** | IAM, S3 bucket, Redshift cluster, tables | *Setting Up Your AWS Environment* |
| 2 | **Extract** | `etl-scraper` Lambda hits 3 APIs → raw CSVs in S3 | *Building the ETL Pipeline with Lambda* |
| 3 | **Transform + Load** | `etl-transformer` Lambda cleans each file → `COPY` into Redshift | *Building the ETL Pipeline with Lambda* |
| 4 | **Automate** | EventBridge schedule (15 min) + S3 event trigger | *(covered across the ETL talks)* |
| 5 | **Analyze** | Query the loaded data in Redshift | *Data Analytics with Amazon Redshift* |
| 6 | **Visualize** | Build dashboards on top of Redshift | *Creating Dashboards with Amazon Redshift* |

---

## The data

Three live, free, **keyless** public datasets — no API keys to manage:

| Dataset | Source | Cities / scope |
|---------|--------|----------------|
| **Weather** | [Open-Meteo](https://open-meteo.com/) | Manila, Cebu, Davao |
| **Air quality** | Open-Meteo air-quality API | Manila, Cebu, Davao (PM2.5, PM10, CO, ozone) |
| **Earthquakes** | [USGS](https://earthquake.usgs.gov/) | Recent quakes in a box around the Philippines |

Each scraper run writes **three** raw CSVs (one per dataset), so one run flows
three files through the whole pipeline.

---

## Where the data lands (Redshift tables)

All three tables live in the `public` schema and carry an `ingested_at` timestamp
(when the scrape happened, UTC).

| Table | Key columns |
|-------|-------------|
| `public.weather` | `city, observed_at, temperature_c, temperature_f, humidity_pct, wind_kph` |
| `public.air_quality` | `city, observed_at, pm2_5, pm10, carbon_monoxide, ozone` |
| `public.earthquakes` | `event_id, occurred_at, magnitude, depth_km, latitude, longitude, place` |

Full definitions: [`sql/ddl.sql`](../sql/ddl.sql).

---

## AWS services you'll touch

- **S3** — the data lake. Raw files under `raw/`, cleaned files under `processed/`.
- **Lambda** — two functions (Python 3.12): the scraper and the transformer.
- **EventBridge Scheduler** — fires the scraper every 15 minutes.
- **Redshift** — the data warehouse you load into and query.
- **Redshift Data API** — how the transformer runs `COPY` without a DB connection.
- **IAM** — the roles/policies that let these services talk to each other securely.
- **CloudWatch Logs** — where you debug when something doesn't fire.

Everything stays in **one region** (`ap-southeast-1`, Singapore — closest to PH).
Mixing regions breaks the Redshift `COPY`.

---

## What you'll learn

- How an **event-driven, serverless** architecture differs from a cron script on a server.
- The **ETL pattern** — Extract, Transform, Load — with real, messy live data.
- How **S3 events** and **EventBridge schedules** wire services together with zero glue servers.
- How to load into and **query a columnar warehouse** (Redshift).
- The **IAM permission model** — which role does what, and why COPY needs a *separate* role from the Lambda.
- How to turn warehouse data into a **dashboard**.

---

## Prerequisites

- An AWS account access (your facilitator will confirm how you're signed in).
- Basic Python reading ability (you'll paste and read provided code — not write it from scratch).
- Basic SQL (`SELECT`, `COUNT`, `JOIN`) helps for the analytics section.
- A browser. That's it — no local installs required; all code runs in the Lambda console.

---

## How to follow along

1. **[`docs/RUNBOOK.md`](RUNBOOK.md)** — the step-by-step console guide. This is your
   primary hands-on reference; follow it top to bottom.
2. **[`README.md`](../README.md)** — high-level architecture and repo layout.
3. Code you'll deploy:
   - [`etl/scraper/main.py`](../etl/scraper/main.py) — the extract step.
   - [`etl/transformer/main.py`](../etl/transformer/main.py) — the transform + load step.
4. **[`sql/ddl.sql`](../sql/ddl.sql)** — run once in the Redshift query editor to create the tables.

---

## ⚠️ Important: cost & cleanup

- **S3 and Lambda are effectively free** for this workshop.
- **Redshift bills by the hour** (~$0.65/hr for the `ra3.large` node) the *entire time
  the cluster exists* — not just while querying.
- **Tear everything down the same day.** Follow [Teardown in the RUNBOOK](RUNBOOK.md#7-teardown-do-this):
  delete the schedule → delete the cluster → empty & delete the bucket → delete the Lambdas & roles.

When in doubt, ask a facilitator before deleting shared resources.

---

## Quick win — prove it works

Once your pipeline is deployed, run this in the Redshift **Query editor v2** and watch
the counts climb every 15 minutes:

```sql
SELECT COUNT(*) FROM public.weather;
SELECT COUNT(*) FROM public.air_quality;
SELECT event_id, magnitude, place
FROM public.earthquakes
ORDER BY occurred_at DESC
LIMIT 10;
```

Rows in all three tables = your event-driven pipeline is alive. 🎉
