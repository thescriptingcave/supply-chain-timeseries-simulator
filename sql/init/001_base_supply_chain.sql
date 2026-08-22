CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS public.sc_vehicles (
    vehicle_id SERIAL PRIMARY KEY,
    vehicle_reg TEXT NOT NULL UNIQUE,
    vehicle_type TEXT,
    max_payload_kg NUMERIC(8,2),
    fuel_type TEXT,
    fleet_operator TEXT,
    year_manufactured INTEGER DEFAULT 2020
);

CREATE TABLE IF NOT EXISTS public.sc_warehouses (
    warehouse_id SERIAL PRIMARY KEY,
    warehouse_name TEXT NOT NULL,
    lat NUMERIC(10,6),
    lon NUMERIC(10,6),
    timezone TEXT DEFAULT 'UTC',
    capacity_pallets INTEGER,
    wh_type TEXT DEFAULT 'DISTRIBUTION'
);

CREATE TABLE IF NOT EXISTS public.sc_shipments (
    shipment_id SERIAL PRIMARY KEY,
    vehicle_id INTEGER REFERENCES public.sc_vehicles(vehicle_id),
    origin_wh_id INTEGER REFERENCES public.sc_warehouses(warehouse_id),
    dest_wh_id INTEGER REFERENCES public.sc_warehouses(warehouse_id),
    cargo_type TEXT,
    scheduled_departure TIMESTAMPTZ,
    scheduled_arrival TIMESTAMPTZ,
    actual_departure TIMESTAMPTZ,
    actual_arrival TIMESTAMPTZ,
    status TEXT,
    priority TEXT DEFAULT 'STANDARD'
);

CREATE TABLE IF NOT EXISTS public.sc_fleet_telemetry (
    time TIMESTAMPTZ NOT NULL,
    vehicle_id INTEGER REFERENCES public.sc_vehicles(vehicle_id),
    shipment_id INTEGER REFERENCES public.sc_shipments(shipment_id),
    lat NUMERIC(10,6),
    lon NUMERIC(10,6),
    speed_kmh NUMERIC(5,2),
    heading_deg NUMERIC(5,2),
    altitude_m NUMERIC(7,2),
    engine_rpm INTEGER,
    fuel_level_pct NUMERIC(5,2),
    coolant_temp_c NUMERIC(5,2),
    cargo_temp_c NUMERIC(5,2),
    cargo_humidity_pct NUMERIC(5,2),
    door_open BOOLEAN,
    harsh_braking BOOLEAN,
    harsh_acceleration BOOLEAN,
    idle_time_sec INTEGER,
    odometer_km NUMERIC(10,3),
    geofence_zone TEXT
);
SELECT create_hypertable('public.sc_fleet_telemetry', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS public.sc_warehouse_env (
    time TIMESTAMPTZ NOT NULL,
    warehouse_id INTEGER REFERENCES public.sc_warehouses(warehouse_id),
    zone TEXT,
    temp_c NUMERIC(5,2),
    humidity_pct NUMERIC(5,2),
    co2_ppm NUMERIC(7,2),
    occupancy_count INTEGER,
    energy_kwh NUMERIC(8,3),
    door_events INTEGER
);
SELECT create_hypertable('public.sc_warehouse_env', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS public.sc_events (
    time TIMESTAMPTZ NOT NULL,
    event_id TEXT,
    shipment_id INTEGER REFERENCES public.sc_shipments(shipment_id),
    event_type TEXT,
    location_lat NUMERIC(10,6),
    location_lon NUMERIC(10,6),
    warehouse_id INTEGER REFERENCES public.sc_warehouses(warehouse_id),
    detail_json JSONB,
    severity TEXT
);
SELECT create_hypertable('public.sc_events', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

INSERT INTO public.sc_vehicles (vehicle_reg, vehicle_type, max_payload_kg, fuel_type, fleet_operator, year_manufactured) VALUES
('TX-7842-TR', 'TRUCK', 24000, 'DIESEL', 'Swift Transport', 2021),
('CA-9911-RF', 'REEFER', 22000, 'DIESEL', 'Cold Chain Logistics', 2022),
('AZ-4455-TK', 'TANKER', 30000, 'DIESEL', 'PetroHaul Inc', 2020),
('NM-1122-VN', 'VAN', 3500, 'ELECTRIC', 'LastMile Delivery', 2023),
('TX-3366-TR', 'TRUCK', 26000, 'DIESEL', 'Swift Transport', 2021),
('CA-7788-RF', 'REEFER', 21000, 'DIESEL', 'Cold Chain Logistics', 2022),
('TX-9900-TK', 'TANKER', 32000, 'DIESEL', 'PetroHaul Inc', 2019),
('AZ-2233-VN', 'VAN', 3200, 'ELECTRIC', 'LastMile Delivery', 2023)
ON CONFLICT (vehicle_reg) DO NOTHING;

INSERT INTO public.sc_warehouses (warehouse_name, lat, lon, timezone, capacity_pallets, wh_type) VALUES
('Houston Distribution Hub', 29.7604, -95.3698, 'America/Chicago', 50000, 'DISTRIBUTION'),
('Los Angeles Port Warehouse', 33.7362, -118.2922, 'America/Los_Angeles', 75000, 'PORT'),
('Phoenix Central DC', 33.4484, -112.0740, 'America/Phoenix', 40000, 'DISTRIBUTION'),
('El Paso Border Facility', 31.7619, -106.4850, 'America/Denver', 30000, 'CROSS_DOCK');
