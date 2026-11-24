# PostgreSQL analitik sorguları

Tam sorgular [SQL dosyasında](../sql/02_analytics_queries.sql), açıklamalar ve çalıştırılmış sonuçlar [notebook’ta](../notebooks/03_sql_analytics.ipynb).

| Kavram | Ne yapar? | Kısa örnek |
|---|---|---|
| `SELECT` | Döndürülecek sütunları seçer. | `SELECT udi, torque FROM public.sensor_readings;` |
| `WHERE` | Koşulu sağlayan satırları tutar. | `SELECT udi FROM public.sensor_readings WHERE torque > 50;` |
| `ORDER BY` | Çıktıyı sıralar. `DESC` azalan sıradır. | `SELECT udi, torque FROM public.sensor_readings ORDER BY torque DESC, udi;` |
| `LIMIT` | Döndürülecek en fazla satır sayısını belirtir. | `SELECT udi FROM public.sensor_readings ORDER BY udi LIMIT 10;` |
| `COUNT` | `COUNT(*)` satırları, `COUNT(sütun)` boş olmayan değerleri sayar. | `SELECT COUNT(*) FROM public.sensor_readings;` |
| `AVG` | Boş olmayan değerlerin ortalamasını alır. | `SELECT AVG(torque) FROM public.sensor_readings;` |
| `SUM` | Değerleri toplar. Bir 0/1 bayrağında 1’leri saymak için kullanılabilir. | `SELECT SUM(machine_failure) FROM public.failure_records;` |
| `MIN`, `MAX` | En küçük ve en büyük değeri bulur. | `SELECT MIN(torque), MAX(torque) FROM public.sensor_readings;` |
| `GROUP BY` | Aynı anahtar değerine sahip satırları özetler. | `SELECT type_code, COUNT(*) FROM public.sensor_readings GROUP BY type_code;` |
| `HAVING` | Grupları toplama işleminden sonra filtreler. | `SELECT type_code FROM public.sensor_readings GROUP BY type_code HAVING COUNT(*) >= 2000;` |
| `INNER JOIN` | İki tarafta da eşleşen satırları alır. | `SELECT s.udi, f.machine_failure FROM public.sensor_readings s INNER JOIN public.failure_records f ON f.udi = s.udi;` |
| `LEFT JOIN` | Soldaki tüm satırları korur. Eşleşme yoksa sağdaki sütunlar `NULL` olur. | `SELECT p.type_code, s.udi FROM public.product_types p LEFT JOIN public.sensor_readings s ON s.type_code = p.type_code;` |
| `CASE WHEN` | Koşula göre değer veya etiket üretir. | `SELECT CASE WHEN tool_wear >= 200 THEN 'Yüksek' ELSE 'Diğer' END FROM public.sensor_readings;` |
| Alt sorgu | Başka bir sorgunun sonucunu, örneğin karşılaştırma eşiği olarak kullanır. | `SELECT udi FROM public.sensor_readings WHERE torque > (SELECT AVG(torque) FROM public.sensor_readings);` |
| CTE | `WITH` ile sorgu içinde kullanılacak ara sonuca ad verir. | `WITH totals AS (SELECT COUNT(*) AS n FROM public.sensor_readings) SELECT n FROM totals;` |
| Pencere fonksiyonu | `OVER` ile bir satır grubunda hesap yapar ve her satırı korur. | `SELECT udi, AVG(torque) OVER (PARTITION BY type_code) FROM public.sensor_readings;` |
| `ROW_NUMBER` | Her satıra benzersiz sıra verir. | `SELECT ROW_NUMBER() OVER (PARTITION BY type_code ORDER BY torque DESC, udi) FROM public.sensor_readings;` |
| `RANK` | Eşit değerlere aynı sırayı verir ve sonraki sırada boşluk bırakabilir. | `SELECT RANK() OVER (ORDER BY torque DESC) FROM public.sensor_readings;` |
| `DENSE_RANK` | Eşit değerlere aynı sırayı verir ve sonraki sırada boşluk bırakmaz. | `SELECT DENSE_RANK() OVER (ORDER BY torque DESC) FROM public.sensor_readings;` |
| `EXPLAIN ANALYZE` | Sorguyu çalıştırır ve planı, gerçekleşen süreyi ve satır sayısını gösterir. | `EXPLAIN (ANALYZE, BUFFERS) SELECT torque FROM public.sensor_readings WHERE udi = 1000;` |

Örneğin tork değerleri 80, 80 ve 70 olsaydı `RANK` sıraları 1, 1, 3, `DENSE_RANK` sıraları 1, 1, 2 olurdu. `ROW_NUMBER` sıraları 1, 2, 3 olur. Eşitlikleri tutarlı çözmek için `ROW_NUMBER` sıralamasına UDI eklenir. [PostgreSQL pencere fonksiyonları](https://www.postgresql.org/docs/17/functions-window.html)

`Index Scan` uygun satırları indeks yoluyla bulur. `Sequential Scan` tablo sayfalarını sırayla okur. Küçük tablolarda veya satırların çoğu gerektiğinde sıralı okuma uygun bir plan olabilir. [PostgreSQL EXPLAIN kılavuzu](https://www.postgresql.org/docs/17/using-explain.html)

Takım aşınması eşikleri öğretici örnektir ve gerçek risk modeli oluşturmaz.
