SELECT
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
      'sc_fleet_telemetry',
      'sc_shipments',
      'sc_events',
      'sc_vehicles',
      'sc_routes'
  )
ORDER BY table_name, ordinal_position;