# MLOps ve MLflow

Bu aşamada önceki deneyleri izlenebilir hale getiriyor, XGBoost Pipeline’ının bir kopyasını sürümlüyor ve yeni sensör girdilerini eğitim referansıyla karşılaştırıyoruz.

| Kavram | Projedeki örnek |
| --- | --- |
| **MLOps** | Model geliştirme, doğrulama, sürümleme ve izleme işlerini tekrarlanabilir hale getiren çalışma biçimi. |
| **MLflow** | Run’ları, dosyaları ve kayıtlı model sürümlerini tek yerden incelemeyi sağlayan araç. |
| **Experiment Tracking** | Hangi veri, ayar ve ölçümün hangi deneye ait olduğunu kaydetmek. |
| **Run** | Experiment içindeki bir değerlendirme kaydı. Örneğin XGBoost çapraz doğrulaması bir run’dır. |
| **Parameters** | Deney ayarları. Örneğin XGBoost’un ağaç derinliği ve MLP’nin epoch sayısı. |
| **Metrics** | Bir değerlendirmeden ölçülmüş sayılar. Örneğin XGBoost çapraz doğrulama Average Precision değeri 0,7643. |
| **Artifacts** | Run ile saklanan dosyalar. Örneğin doğrulama CSV’si, ROC grafiği ve model metadata’sı. |
| **Model Registry** | Model kopyalarını, kaynak run’larını ve doğrulama bilgilerini saklayan katalog. |
| **Model Versioning** | Model kopyalarına sürüm numarası vermek. Registry’deki v1 ve kaynak model sürümü 1.0.0 ayrı tanımlayıcılardır. |
| **Data Drift** | Girdilerin dağılım değişimi. Örneğin saklanan akışta yüksek tork ölçümleri eğitim referansına göre daha sık görülebilir. |
| **Concept Drift** | Girdilerle doğru sonuç arasındaki ilişkinin değişmesi. Örneğin aynı torkun arızayla ilişkisi makine bakımı sonrası değişebilir. Bunu değerlendirmek için gözlenen arıza etiketleri gerekir. |
| **Model Monitoring** | Yeni girdilerin kalitesini ve dağılımını düzenli kontrol etmek. Gerçek etiketler geldiğinde model hataları da izlenebilir. |
| **CI/CD** | Değişiklik sonrası test ve paketleme, ardından onaylanmış bir sürümü dağıtma işlemlerini otomatikleştirmek. Buradaki testler ileride CI adımı olabilir. Dağıtım otomasyonu bu aşamada elle yönetilir. |

## Yerel kullanım

MLflow 3.18.0, Python 3.10 ve üzeri gerektirir. Projenin Python 3.12 ortamı kullanılır. SQLite `.mlflow/tracking.db` altında run ve Registry metadata’sını tutar. Dosyalar `.mlflow/artifacts/` altında saklanır. Her iki konum Git kapsamı dışındadır. [MLflow 3.18.0 paket bilgileri](https://pypi.org/project/mlflow/3.18.0/) · [Tracking Server kılavuzu](https://www.mlflow.org/docs/latest/self-hosting/architecture/tracking-server/)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File mlops/start_tracking.ps1
```

İkinci terminalde, mevcut PostgreSQL hazırken:

```powershell
.\.venv\Scripts\python.exe -m mlops.tracking
.\.venv\Scripts\python.exe -m mlops.register_model
.\.venv\Scripts\python.exe -m mlops.monitoring --limit 1000
```

[MLflow arayüzü](http://127.0.0.1:5000/) · [Dashboard Model Analytics](http://127.0.0.1:5080/model-analytics)

IndustryPulseAI experiment’inde **Training runs** sekmesi, `origin=imported` etiketiyle yedi çapraz doğrulama run’ı ve ayrı bir XGBoost bağımsız test run’ı içerir. `evaluation_split` filtresi karşılaştırılabilir sonuçları ayırır. Kaynak CSV’de ölçülmemiş değerler eklenmez. Aynı değerlendirme verisi ve parametreler yeniden girildiğinde run kimlikleri korunur.

Registry’ye kaydedilen Pipeline, mevcut yerel joblib dosyasından yüklenir. Yeniden yüklenen sınıflar ve skorlar 8.000 eğitim kaydında eşleşirse sürüme `verified` alias’ı verilir. Aynı kaynağın SHA-256 özeti Registry sürümünün tekrar kullanılmasını sağlar. FastAPI mevcut joblib dosyasını kullanır. Bağımsız test verisi optimizasyon için kullanılmaz. [Model Registry kılavuzu](https://mlflow.org/docs/latest/model-registry/)

## Drift raporu

Referans önceki tabakalı ayrımdaki 8.000 eğitim kaydıdır. Akış örneği, en güncel 1.000 PostgreSQL olayıyla sınırlıdır. Sayısal alanlarda iki ampirik birikimli dağılım arasındaki en büyük farkı ölçen KS istatistiği, ürün tipinde toplam varyasyon uzaklığı kullanılır. Her ikisi 0–1 aralığındadır. Bu eğitim örneğinde KS ≥ 0,20 veya toplam varyasyon ≥ 0,15 inceleme işaretidir. Eşikler örnek amaçlıdır. 30 geçerli kayıt bulunmadığında sonuç `insufficient_data` olur.

Rapor eksik veya sonlu olmayan girdileri, negatif ya da geçersiz değerleri ve sayısal referans aralığı dışındaki kayıtları sayar. Saklanan olaylar sentetik CSV’den tekrar oynatılmıştır. Bu örnekleme dağılım farkları oluşturabilir. Canlı arıza etiketi olmadığından Accuracy, Recall veya Concept Drift ölçülmez ve gerçek üretim performansı hakkında sonuç çıkarılmaz.

## Doğrulama

```powershell
$env:RUN_MLFLOW_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mlops.py -v
Remove-Item Env:RUN_MLFLOW_TESTS
```

[Çalıştırılmış MLOps notebook’u](../notebooks/07_mlops_mlflow.ipynb) · [Mevcut Kafka ve Spark test ortamları](spark_processing.md#çalıştırma)
