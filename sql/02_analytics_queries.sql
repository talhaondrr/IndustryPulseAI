-- IndustryPulseAI PostgreSQL 17 analizleri. Tüm sorgular okuma amaçlıdır.

-- name: overview
-- COUNT satırları, SUM arızaları sayar. AVG üzerinden oran, MIN/MAX ile tork aralığı.
SELECT count(*) AS total_records,
       sum(machine_failure) AS failure_count,
       count(*) FILTER (WHERE machine_failure = 0) AS normal_count,
       round(100 * avg(machine_failure), 2) AS failure_rate_pct,
       round(avg(torque), 5) AS avg_torque_nm,
       min(torque) AS min_torque_nm,
       max(torque) AS max_torque_nm
FROM public.ml_training_data;

-- name: product_rates
-- LEFT JOIN ile ölçümü bulunmayan tipler korunur. Payda, etiketli ölçüm sayısıdır.
SELECT p.type_code, p.type_name,
       count(s.udi) AS reading_count,
       count(f.udi) AS labeled_count,
       coalesce(sum(f.machine_failure), 0) AS failure_count,
       round(100 * avg(f.machine_failure), 2) AS failure_rate_pct
FROM public.product_types AS p
LEFT JOIN public.sensor_readings AS s ON s.type_code = p.type_code
LEFT JOIN public.failure_records AS f ON f.udi = s.udi
GROUP BY p.type_code, p.type_name
ORDER BY p.type_code;

-- name: product_groups
-- HAVING, kayıt sayısı hesaplandıktan sonra ürün tipi gruplarını filtreler.
SELECT type_code, count(*) AS reading_count
FROM public.sensor_readings
GROUP BY type_code
HAVING count(*) >= 2000
ORDER BY reading_count DESC, type_code;

-- name: sensor_means
-- INNER JOIN yalnızca ölçümü ve etiketi eşleşen satırları alır.
SELECT f.machine_failure, count(*) AS record_count,
       round(avg(s.air_temperature), 2) AS air_temperature_k,
       round(avg(s.process_temperature), 2) AS process_temperature_k,
       round(avg(s.rotational_speed), 2) AS rotational_speed_rpm,
       round(avg(s.torque), 2) AS torque_nm,
       round(avg(s.tool_wear), 2) AS tool_wear_min
FROM public.sensor_readings AS s
INNER JOIN public.failure_records AS f ON f.udi = s.udi
GROUP BY f.machine_failure
ORDER BY f.machine_failure;

-- name: top_torque
-- ORDER BY en yüksek torku öne alır, UDI eşitlikleri çözer. LIMIT ilk 10 satırı verir.
SELECT udi, product_id, type_code, torque AS torque_nm
FROM public.sensor_readings
ORDER BY torque DESC, udi
LIMIT 10;

-- name: wear_groups
-- Öğretici aşınma eşikleri. Gruplar gerçek bir risk modelini temsil etmez.
WITH grouped_wear AS (
    SELECT machine_failure,
           CASE WHEN tool_wear < 100 THEN 'Düşük'
                WHEN tool_wear < 200 THEN 'Orta'
                ELSE 'Yüksek'
           END AS wear_group
    FROM public.ml_training_data
)
SELECT wear_group, count(*) AS labeled_count,
       sum(machine_failure) AS failure_count,
       round(100 * avg(machine_failure), 2) AS failure_rate_pct
FROM grouped_wear
GROUP BY wear_group
ORDER BY min(CASE wear_group WHEN 'Düşük' THEN 1 WHEN 'Orta' THEN 2 ELSE 3 END);

-- name: torque_ranks
-- Her tipin ilk 10 satırı. Pencere sıralaması tip başına tüm ölçümler üzerinden yapılır.
WITH ranked AS (
    SELECT udi, type_code, torque AS torque_nm,
           row_number() OVER (PARTITION BY type_code ORDER BY torque DESC, udi) AS row_no,
           rank() OVER (PARTITION BY type_code ORDER BY torque DESC) AS torque_rank,
           dense_rank() OVER (PARTITION BY type_code ORDER BY torque DESC) AS dense_torque_rank,
           round(avg(torque) OVER (PARTITION BY type_code), 2) AS type_avg_torque_nm
    FROM public.sensor_readings
)
SELECT udi, type_code, torque_nm, row_no, torque_rank, dense_torque_rank, type_avg_torque_nm
FROM ranked
WHERE row_no <= 10
ORDER BY type_code, row_no;

-- name: failure_modes
-- Her bayrak bağımsız sayılır. Aynı satırda birden fazla bayrak açık olabilir.
WITH totals AS (
    SELECT sum(twf) AS twf, sum(hdf) AS hdf, sum(pwf) AS pwf,
           sum(osf) AS osf, sum(rnf) AS rnf
    FROM public.failure_records
)
SELECT mode.failure_type, mode.record_count
FROM totals
CROSS JOIN LATERAL (
    VALUES ('TWF', twf), ('HDF', hdf), ('PWF', pwf), ('OSF', osf), ('RNF', rnf)
) AS mode(failure_type, record_count)
ORDER BY mode.record_count DESC, mode.failure_type;

-- name: above_average
-- Alt sorgu genel tork ortalamasını üretir. WHERE bu değeri aşan ölçümleri seçer.
SELECT udi, product_id, type_code, torque AS torque_nm
FROM public.sensor_readings
WHERE torque > (SELECT avg(torque) FROM public.sensor_readings)
ORDER BY torque DESC, udi;

-- name: plan_by_udi
-- Seçici bir koşulda birincil anahtar indeksinin plan içindeki rolü.
EXPLAIN (ANALYZE, BUFFERS)
SELECT udi, torque
FROM public.sensor_readings
WHERE udi = 1000;

-- name: plan_full_average
-- Tüm ölçümleri kapsayan bir toplama işleminin planı.
EXPLAIN (ANALYZE, BUFFERS)
SELECT avg(torque)
FROM public.sensor_readings;
