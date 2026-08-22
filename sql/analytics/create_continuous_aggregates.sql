-- Optional TimescaleDB analytical layer. Run after the schema is initialized.

CREATE MATERIALIZED VIEW IF NOT EXISTS sc_fleet_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    vehicle_id,
    COUNT(*) AS sample_count,
    AVG(speed_kmh) AS avg_speed_kmh,
    MAX(speed_kmh) AS max_speed_kmh,
    AVG(engine_rpm) AS avg_engine_rpm,
    MAX(engine_rpm) AS max_engine_rpm,
    AVG(fuel_level_pct) AS avg_fuel_level_pct,
    MIN(fuel_level_pct) AS min_fuel_level_pct,
    AVG(cargo_temp_c) AS avg_cargo_temp_c,
    MIN(cargo_temp_c) AS min_cargo_temp_c,
    MAX(cargo_temp_c) AS max_cargo_temp_c,
    COUNT(*) FILTER (WHERE harsh_braking) AS harsh_brake_count,
    COUNT(*) FILTER (WHERE harsh_acceleration) AS harsh_accel_count,
    COUNT(*) FILTER (WHERE door_open) AS door_open_samples
FROM sc_fleet_telemetry
GROUP BY bucket, vehicle_id
WITH NO DATA;
