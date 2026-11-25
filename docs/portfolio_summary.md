# IndustryPulseAI portföy özeti

## Türkçe CV proje açıklaması

PostgreSQL, Kafka ve Spark ile uçtan uca bir kestirimci bakım prototipi geliştirdim. Sentetik AI4I 2020 verisindeki 10.000 ölçümü işledim ve yedi modeli beş katlı çapraz doğrulamayla karşılaştırdım. XGBoost Pipeline’ını FastAPI ile sundum, ASP.NET Core MVC Dashboard’a entegre ettim ve deneyleri ve doğrulanmış model sürümünü MLflow’da izlenebilir hale getirdim.

## English CV project description

Built an end-to-end predictive maintenance prototype using PostgreSQL, Kafka and Spark. Processed 10,000 synthetic AI4I records and evaluated seven classifiers with five-fold cross-validation. Served the selected XGBoost pipeline through FastAPI and an ASP.NET Core MVC dashboard, and verified model lineage and reload parity in MLflow.

## Kullanılan teknolojiler

Python, Pandas, Psycopg, PostgreSQL, Docker Compose, Apache Kafka KRaft, PySpark, scikit-learn, XGBoost, PyTorch, FastAPI, ASP.NET Core MVC, Razor, Chart.js, MLflow, SQLite ve GitHub Actions.

## Ölçülebilir proje sonuçları

| Ölçüm | Sonuç |
| --- | --- |
| Veri | 10.000 kayıt, 339 arıza, %3,39 arıza oranı |
| Model karşılaştırması | Yedi model, beş tabakalı kat, XGBoost doğrulama AP 0,7643 |
| Bağımsız XGBoost testi | AP 0,8429, Recall 0,8971, 68 arızanın 61’i yakalandı |
| Kafka uçtan uca | 100 benzersiz olay, 0 kayıp, 0 tekrar |
| Spark ve PostgreSQL | 100 yeni kayıt doğrulandı, tekrar gönderimde 0 mükerrer satır |
| Model sürümü | MLflow v1 yeniden yüklendi, 8.000 sınıf ve skor yerel Pipeline ile eşleşti |
| Yerel regresyon | 45 Python testi, hatasız ve uyarısız MVC Release derlemesi |

## Teknik mülakatta anlatılabilecek mimari kararlar

- **Veri sızıntısını önleme.** Kimlik ve arıza türü göstergeleri modelden çıkarıldı. Ön işleme her katın eğitim bölümünde fit edildi.
- **Model seçimi.** Sınıf dengesizliği nedeniyle Average Precision öne alındı. Bağımsız test, model seçimi bittikten sonra XGBoost için kullanıldı.
- **Tekrarlanabilir akış.** Kafka offset sınırı yeni olayları geçmişten ayırır. Spark checkpoint yeniden başlatmayı, PostgreSQL UUID anahtarı tekrar yazımın idempotent olmasını sağlar.
- **Sorumluluk ayrımı.** MVC arayüzü HTTP ile FastAPI’ye erişir. Tahmin Pipeline’ı ve salt okunur SQL sorguları servis katmanında kalır.
- **Deney izlenebilirliği.** MLflow geçmiş metrikleri içe aktarılmış olarak etiketler. Registry alias’ı tahmin paritesi doğrulanmış sürümü işaret eder.

## Sınırlamalar

Veri seti sentetiktir. Spark **`local[2]`** modunda, Kafka tek broker ile çalışır. XGBoost skoru kalibre edilmiş gerçek dünya arıza olasılığı değildir. Akışta gerçek arıza etiketleri bulunmadığından izleme girdi kalitesi ve dağılım değişimiyle sınırlıdır. Yerel sonuçlar gerçek fabrikadaki başarıyı veya üretim ölçeğini garanti etmez.
