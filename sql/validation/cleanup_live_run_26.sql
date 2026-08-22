SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS row_count
    FROM sc_fleet_telemetry
    WHERE run_id = 30
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;