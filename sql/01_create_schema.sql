CREATE TABLE IF NOT EXISTS public.product_types (
    type_code text PRIMARY KEY CHECK (type_code IN ('L', 'M', 'H')),
    type_name text NOT NULL CHECK (btrim(type_name) <> ''),
    description text
);

CREATE TABLE IF NOT EXISTS public.sensor_readings (
    udi integer PRIMARY KEY CHECK (udi > 0),
    product_id text NOT NULL CHECK (btrim(product_id) <> ''),
    type_code text NOT NULL REFERENCES public.product_types (type_code),
    air_temperature numeric NOT NULL CHECK (air_temperature > 0 AND air_temperature < 'Infinity'::numeric),
    process_temperature numeric NOT NULL CHECK (process_temperature > 0 AND process_temperature < 'Infinity'::numeric),
    rotational_speed integer NOT NULL CHECK (rotational_speed >= 0),
    torque numeric NOT NULL CHECK (torque >= 0 AND torque < 'Infinity'::numeric),
    tool_wear integer NOT NULL CHECK (tool_wear >= 0)
);

CREATE TABLE IF NOT EXISTS public.failure_records (
    udi integer PRIMARY KEY REFERENCES public.sensor_readings (udi),
    machine_failure smallint NOT NULL CHECK (machine_failure IN (0, 1)),
    twf smallint NOT NULL CHECK (twf IN (0, 1)),
    hdf smallint NOT NULL CHECK (hdf IN (0, 1)),
    pwf smallint NOT NULL CHECK (pwf IN (0, 1)),
    osf smallint NOT NULL CHECK (osf IN (0, 1)),
    rnf smallint NOT NULL CHECK (rnf IN (0, 1))
);

COMMENT ON COLUMN public.sensor_readings.air_temperature IS 'Air temperature in kelvins (K).';
COMMENT ON COLUMN public.sensor_readings.process_temperature IS 'Process temperature in kelvins (K).';
COMMENT ON COLUMN public.sensor_readings.rotational_speed IS 'Rotational speed in revolutions per minute (rpm).';
COMMENT ON COLUMN public.sensor_readings.torque IS 'Torque in newton-metres (N·m).';
COMMENT ON COLUMN public.sensor_readings.tool_wear IS 'Tool wear in minutes (min).';

CREATE INDEX IF NOT EXISTS sensor_readings_type_code_idx
    ON public.sensor_readings (type_code);

CREATE OR REPLACE VIEW public.ml_training_data AS
SELECT
    s.type_code,
    s.air_temperature,
    s.process_temperature,
    s.rotational_speed,
    s.torque,
    s.tool_wear,
    f.machine_failure
FROM public.sensor_readings AS s
JOIN public.failure_records AS f USING (udi);
