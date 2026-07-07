# AWS ETL Pipeline — Workshop

A hands-on, fully **serverless ETL pipeline** on AWS. A scheduled Lambda scrapes
three Philippine datasets from free, keyless APIs, lands raw CSV in an S3 data
lake, and a second Lambda transforms each file and loads it into the matching
Redshift table via `COPY`.

Datasets:

- **Weather** — [Open-Meteo](https://open-meteo.com/) current conditions (Manila / Cebu / Davao)
- **Air quality** — Open-Meteo air-quality API (same cities: PM2.5, PM10, CO, ozone)
- **Earthquakes** — [USGS](https://earthquake.usgs.gov/) recent quakes near the Philippines

Built as a teaching demo — deploy it by clicking through the AWS Console using
[`docs/RUNBOOK.md`](docs/RUNBOOK.md). No IaC, no framework, no third-party Python
packages (standard library + preinstalled `boto3` only).

## Architecture

```
 EventBridge (rate: 15 min)
        │
        ▼
 ┌─────────────────┐  HTTPS   ┌──────────────────────────────┐
 │  Lambda:        │ ───────► │ Open-Meteo weather           │
 │  etl-scraper    │ ───────► │ Open-Meteo air quality       │
 │  (3 datasets)   │ ───────► │ USGS earthquakes (PH bbox)   │
 └────────┬────────┘          └──────────────────────────────┘
          │ writes 3 raw CSVs
          ▼
 ┌───────────────────────────── S3 (data lake) ──────────────────────────────┐
 │  raw/weather/…      raw/air_quality/…      raw/earthquakes/…               │
 │  processed/weather/…   processed/air_quality/…   processed/earthquakes/…   │
 └─────────┬─────────────────────────────────────────────▲───────────────────┘
           │ ObjectCreated (prefix raw/) — fires once per file
           ▼                                              │ writes processed CSV
    ┌──────────────────┐                                  │
    │  Lambda:         │  reads key → routes by dataset ──┘
    │  etl-transformer │  COPY via Redshift Data API
    └────────┬─────────┘
             ▼
    ┌──────────────────────────────────────────────┐
    │  Redshift                                     │
    │  public.weather · air_quality · earthquakes   │
    └──────────────────────────────────────────────┘
```

**How routing works:** one `raw/` S3 trigger covers all three datasets. The
transformer reads the object key (`raw/weather/…` vs `raw/air_quality/…` vs
`raw/earthquakes/…`), picks the matching transform + target table, and `COPY`s the
processed file in. A single scraper run therefore invokes the transformer three
times, once per file.

## Repo layout

```
etl/
  scraper/main.py         # EXTRACT: 3 APIs -> 3 raw CSVs in S3
  transformer/main.py     # TRANSFORM + LOAD: raw CSV -> processed CSV -> Redshift COPY (routed)
sql/ddl.sql               # 3 destination tables
docs/RUNBOOK.md           # console setup, step by step (+ teardown)
docker/                   # optional local test harness
```

## Tables

| table | key columns |
|-------|-------------|
| `public.weather` | `city, observed_at, temperature_c, temperature_f, humidity_pct, wind_kph` |
| `public.air_quality` | `city, observed_at, pm2_5, pm10, carbon_monoxide, ozone` |
| `public.earthquakes` | `event_id, occurred_at, magnitude, depth_km, latitude, longitude, place` |

All three also carry `ingested_at` (scrape timestamp, UTC).

## Quick start

See [`docs/RUNBOOK.md`](docs/RUNBOOK.md). In short:

1. Create S3 bucket + Redshift cluster (public) + COPY IAM role.
2. Run [`sql/ddl.sql`](sql/ddl.sql) in the Redshift query editor (creates all 3 tables).
3. Deploy `etl-scraper` (env `BUCKET`) + EventBridge schedule.
4. Deploy `etl-transformer` (env vars for bucket + Redshift) + S3 `raw/` trigger.
5. Trigger the scraper, then `SELECT COUNT(*)` on each table.

> ⚠️ **Tear down the Redshift cluster and S3 bucket when done** — Redshift bills by the hour.

## Local testing

The scraper runs locally with AWS credentials + `BUCKET`:

```bash
BUCKET=my-test-bucket python etl/scraper/main.py
```

The transformer's per-dataset transform functions (`transform_weather`,
`transform_air_quality`, `transform_earthquakes`) are plain functions you can call
directly on sample rows without any AWS calls.
