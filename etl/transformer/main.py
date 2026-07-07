"""
Transformer Lambda — the TRANSFORM + LOAD step.

Triggered by an S3 ObjectCreated event on the raw/ prefix. It inspects the key to
figure out WHICH dataset the file belongs to (weather / air_quality /
earthquakes), applies the matching light transforms, writes a processed CSV under
processed/<dataset>/, then loads it into the matching Redshift table with a COPY
issued through the Redshift Data API (no DB driver, no VPC, no connection string).

Runtime: python3.12. Standard library + boto3 only — no packaging / layer.

Environment variables:
  BUCKET                  (required)  S3 bucket (same as scraper)
  REDSHIFT_CLUSTER_ID     (required)  provisioned cluster identifier
  REDSHIFT_DB             (required)  database name
  REDSHIFT_USER           (required)  master/db user for temp credentials
  REDSHIFT_COPY_ROLE_ARN  (required)  IAM role ARN attached to the cluster for COPY
"""

import csv
import io
import json
import os
import urllib.parse

import boto3

s3 = boto3.client("s3")
redshift_data = boto3.client("redshift-data")


# ---- per-dataset transforms -------------------------------------------------
# Each transform takes a list of raw dict rows and returns cleaned dict rows.

def _f(row, key):
    """Float or None if missing/blank."""
    v = row.get(key)
    return None if v in (None, "") else float(v)


def transform_weather(rows):
    out, seen = [], set()
    for r in rows:
        if not r.get("city") or _f(r, "temperature_c") is None:
            continue
        k = (r["city"], r["observed_at"])
        if k in seen:
            continue
        seen.add(k)
        temp_c = _f(r, "temperature_c")
        out.append({
            "city": r["city"],
            "observed_at": r["observed_at"],
            "temperature_c": round(temp_c, 2),
            "temperature_f": round(temp_c * 9 / 5 + 32, 2),
            "humidity_pct": int(_f(r, "humidity_pct")),
            "wind_kph": round(_f(r, "wind_kph"), 2),
            "ingested_at": r["ingested_at"],
        })
    return out


def transform_air_quality(rows):
    out, seen = [], set()
    for r in rows:
        if not r.get("city") or _f(r, "pm2_5") is None:
            continue
        k = (r["city"], r["observed_at"])
        if k in seen:
            continue
        seen.add(k)
        out.append({
            "city": r["city"],
            "observed_at": r["observed_at"],
            "pm2_5": round(_f(r, "pm2_5"), 2),
            "pm10": round(_f(r, "pm10"), 2),
            "carbon_monoxide": round(_f(r, "carbon_monoxide"), 2),
            "ozone": round(_f(r, "ozone"), 2),
            "ingested_at": r["ingested_at"],
        })
    return out


def transform_earthquakes(rows):
    out, seen = [], set()
    for r in rows:
        # Drop rows without an id or a usable magnitude.
        if not r.get("event_id") or _f(r, "magnitude") is None:
            continue
        if r["event_id"] in seen:
            continue
        seen.add(r["event_id"])
        out.append({
            "event_id": r["event_id"],
            "occurred_at": r["occurred_at"],
            "magnitude": round(_f(r, "magnitude"), 1),
            "depth_km": round(_f(r, "depth_km"), 2),
            "latitude": round(_f(r, "latitude"), 4),
            "longitude": round(_f(r, "longitude"), 4),
            "place": r.get("place") or "",
            "ingested_at": r["ingested_at"],
        })
    return out


# ---- routing table ----------------------------------------------------------
# prefix under raw/  ->  (Redshift table, output header, transform fn)

DATASETS = {
    "weather": (
        "public.weather",
        ["city", "observed_at", "temperature_c", "temperature_f",
         "humidity_pct", "wind_kph", "ingested_at"],
        transform_weather,
    ),
    "air_quality": (
        "public.air_quality",
        ["city", "observed_at", "pm2_5", "pm10", "carbon_monoxide",
         "ozone", "ingested_at"],
        transform_air_quality,
    ),
    "earthquakes": (
        "public.earthquakes",
        ["event_id", "occurred_at", "magnitude", "depth_km", "latitude",
         "longitude", "place", "ingested_at"],
        transform_earthquakes,
    ),
}


def _dataset_for_key(key):
    """raw/<dataset>/file.csv -> dataset name. Raises if not recognized."""
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != "raw" or parts[1] not in DATASETS:
        raise ValueError(f"Unexpected key layout: {key}")
    return parts[1]


def load_to_redshift(table, bucket, key):
    """Issue a COPY into the given table via the Redshift Data API."""
    copy_sql = (
        f"COPY {table} "
        f"FROM 's3://{bucket}/{key}' "
        f"IAM_ROLE '{os.environ['REDSHIFT_COPY_ROLE_ARN']}' "
        "CSV IGNOREHEADER 1 "
        "TIMEFORMAT 'auto';"
    )
    resp = redshift_data.execute_statement(
        ClusterIdentifier=os.environ["REDSHIFT_CLUSTER_ID"],
        Database=os.environ["REDSHIFT_DB"],
        DbUser=os.environ["REDSHIFT_USER"],
        Sql=copy_sql,
    )
    return resp["Id"]


def handler(event, context):
    bucket = os.environ["BUCKET"]

    record = event["Records"][0]["s3"]
    src_key = urllib.parse.unquote_plus(record["object"]["key"])

    dataset = _dataset_for_key(src_key)
    table, header, transform = DATASETS[dataset]

    # Read raw CSV.
    obj = s3.get_object(Bucket=bucket, Key=src_key)
    raw_rows = list(csv.DictReader(io.StringIO(obj["Body"].read().decode("utf-8"))))

    # Transform.
    clean_rows = transform(raw_rows)

    # Write processed CSV under processed/<dataset>/...
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header)
    writer.writeheader()
    writer.writerows(clean_rows)

    dst_key = src_key.replace("raw/", "processed/", 1)
    s3.put_object(Bucket=bucket, Key=dst_key, Body=buffer.getvalue().encode("utf-8"))

    # Load into the matching Redshift table.
    statement_id = load_to_redshift(table, bucket, dst_key)

    result = {
        "dataset": dataset,
        "table": table,
        "source": src_key,
        "processed": dst_key,
        "rows_loaded": len(clean_rows),
        "redshift_statement_id": statement_id,
    }
    print(json.dumps(result))
    return result
