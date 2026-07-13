"""
Scraper Lambda — the EXTRACT step. (Dynamic City Version)

Fetches Philippine datasets from free, keyless APIs.
Automatically resolves city names to latitude/longitude using the Open-Meteo Geocoding API.
"""

import csv
import io
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import boto3

s3 = boto3.client("s3")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

CITY_NAMES = [
    "Manila",
    "Cebu",
    "Davao",
]

PH_BBOX = {"minlat": 4, "maxlat": 21, "minlon": 116, "maxlon": 127}

WEATHER_HEADER = [
    "city", "observed_at", "temperature_c", "humidity_pct", "wind_kph", "ingested_at",
]
AIR_QUALITY_HEADER = [
    "city", "observed_at", "pm2_5", "pm10", "carbon_monoxide", "ozone", "ingested_at",
]
EARTHQUAKE_HEADER = [
    "event_id", "occurred_at", "magnitude", "depth_km", "latitude", "longitude",
    "place", "ingested_at",
]

_RESOLVED_CITIES = []


def _get_json(url, params):
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{query}", timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_resolved_cities():
    """Look up coordinates for each city in CITY_NAMES and cache them."""
    global _RESOLVED_CITIES
    if _RESOLVED_CITIES:
        return _RESOLVED_CITIES
        
    resolved = []
    for name in CITY_NAMES:
        data = _get_json(GEOCODE_URL, {"name": name, "count": 1})
        if "results" in data and data["results"]:
            lat = data["results"][0]["latitude"]
            lon = data["results"][0]["longitude"]
            resolved.append((name, lat, lon))
        else:
            print(f"Warning: Could not find coordinates for city '{name}'")
            
    _RESOLVED_CITIES = resolved
    return _RESOLVED_CITIES


def fetch_weather(ingested_at, cities):
    rows = []
    for name, lat, lon in cities:
        data = _get_json(
            WEATHER_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            },
        )
        c = data["current"]
        rows.append(
            {
                "city": name,
                "observed_at": c["time"],
                "temperature_c": c["temperature_2m"],
                "humidity_pct": c["relative_humidity_2m"],
                "wind_kph": c["wind_speed_10m"],
                "ingested_at": ingested_at,
            }
        )
    return rows


def fetch_air_quality(ingested_at, cities):
    rows = []
    for name, lat, lon in cities:
        data = _get_json(
            AIR_QUALITY_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "current": "pm2_5,pm10,carbon_monoxide,ozone",
            },
        )
        c = data["current"]
        rows.append(
            {
                "city": name,
                "observed_at": c["time"],
                "pm2_5": c["pm2_5"],
                "pm10": c["pm10"],
                "carbon_monoxide": c["carbon_monoxide"],
                "ozone": c["ozone"],
                "ingested_at": ingested_at,
            }
        )
    return rows


def fetch_earthquakes(ingested_at):
    data = _get_json(
        USGS_URL,
        {
            "format": "geojson",
            "starttime": "now-7days",
            "minlatitude": PH_BBOX["minlat"],
            "maxlatitude": PH_BBOX["maxlat"],
            "minlongitude": PH_BBOX["minlon"],
            "maxlongitude": PH_BBOX["maxlon"],
            "minmagnitude": 2.5,
            "orderby": "time",
        },
    )
    rows = []
    for feature in data.get("features", []):
        props = feature["properties"]
        lon, lat, depth = feature["geometry"]["coordinates"]
        occurred_at = datetime.fromtimestamp(
            props["time"] / 1000, tz=timezone.utc
        ).isoformat()
        rows.append(
            {
                "event_id": feature["id"],
                "occurred_at": occurred_at,
                "magnitude": props.get("mag"),
                "depth_km": depth,
                "latitude": lat,
                "longitude": lon,
                "place": props.get("place"),
                "ingested_at": ingested_at,
            }
        )
    return rows


def _write_csv(bucket, prefix, dataset, header, rows):
    """Write one dataset's rows to raw/<prefix>/<dataset>_<stamp>.csv."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    key = f"raw/{prefix}/{dataset}_{stamp}.csv"
    clean_bucket = bucket.strip()
    s3.put_object(Bucket=clean_bucket, Key=key, Body=buffer.getvalue().encode("utf-8"))
    return {"key": key, "rows": len(rows)}


def handler(event, context):
    bucket = os.environ["BUCKET"]
    ingested_at = datetime.now(timezone.utc).isoformat()
    
    resolved_cities = get_resolved_cities()

    results = {
        "weather": _write_csv(
            bucket, "weather", "weather", WEATHER_HEADER,
            fetch_weather(ingested_at, resolved_cities),
        ),
        "air_quality": _write_csv(
            bucket, "air_quality", "air_quality", AIR_QUALITY_HEADER,
            fetch_air_quality(ingested_at, resolved_cities),
        ),
        "earthquakes": _write_csv(
            bucket, "earthquakes", "earthquakes", EARTHQUAKE_HEADER,
            fetch_earthquakes(ingested_at),
        ),
    }
    print(json.dumps(results))
    return results


if __name__ == "__main__":
    print(handler({}, None))
