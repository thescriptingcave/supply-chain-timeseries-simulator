SELECT
    time,
    shipment_id,
    event_type,
    cause_code,
    severity,
    detail_json
FROM sc_events
WHERE shipment_id = 9276
  AND cause_code = 'REEFER_TEMP_EXCURSION'
ORDER BY time;