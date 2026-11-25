CREATE TABLE IF NOT EXISTS public.stream_sensor_readings (
    event_id uuid PRIMARY KEY,
    event_time timestamptz NOT NULL,
    product_type text NOT NULL CHECK (product_type IN ('L', 'M', 'H')),
    air_temperature double precision NOT NULL CHECK (air_temperature > 0 AND air_temperature < 'Infinity'),
    process_temperature double precision NOT NULL CHECK (process_temperature > 0 AND process_temperature < 'Infinity'),
    rotational_speed integer NOT NULL CHECK (rotational_speed >= 0),
    torque double precision NOT NULL CHECK (torque >= 0 AND torque < 'Infinity'),
    tool_wear integer NOT NULL CHECK (tool_wear >= 0)
);
