-- Run this once in the Redshift query editor (v2) before deploying the Lambdas.
-- Creates the three destination tables, one per dataset.

CREATE TABLE IF NOT EXISTS public.weather (
    city           VARCHAR(64),
    observed_at    TIMESTAMP,
    temperature_c  DECIMAL(5, 2),
    temperature_f  DECIMAL(5, 2),
    humidity_pct   INTEGER,
    wind_kph       DECIMAL(6, 2),
    ingested_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.air_quality (
    city             VARCHAR(64),
    observed_at      TIMESTAMP,
    pm2_5            DECIMAL(7, 2),
    pm10             DECIMAL(7, 2),
    carbon_monoxide  DECIMAL(8, 2),
    ozone            DECIMAL(8, 2),
    ingested_at      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.earthquakes (
    event_id     VARCHAR(64),
    occurred_at  TIMESTAMP,
    magnitude    DECIMAL(3, 1),
    depth_km     DECIMAL(7, 2),
    latitude     DECIMAL(8, 4),
    longitude    DECIMAL(8, 4),
    place        VARCHAR(256),
    ingested_at  TIMESTAMP
);

-- Handy checks after the pipeline runs:
--   SELECT COUNT(*), MAX(observed_at) FROM public.weather;
--   SELECT COUNT(*), MAX(observed_at) FROM public.air_quality;
--   SELECT event_id, magnitude, place FROM public.earthquakes ORDER BY occurred_at DESC LIMIT 10;
