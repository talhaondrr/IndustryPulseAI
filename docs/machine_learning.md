# Makine öğrenmesi

## Problem ve veri

**Supervised Learning (denetimli öğrenme)**, girdileri bilinen sonuçlarla eşleştirerek bir tahmin kuralı öğrenir. Bu projede **Binary Classification (ikili sınıflandırma)** ile ürün tipi ve beş sensör ölçümünden normal çalışma (0) veya arıza (1) tahmin edilir.

PostgreSQL’deki `public.ml_training_data` görünümü salt okunur işlemle sorgulanır. Sorgu görünümdeki tüm sütunlara göre sıralanır. Aynı değerlere sahip satırlar model girdisi ve hedef açısından eşdeğerdir. Kod 10.000 satır bekler ve mevcut preprocessing modülüyle girdileri ve hedefi doğrular. Kimlikler ve arıza türü bayrakları zaten görünüm dışında tutulur. Arıza türü bayrakları arıza meydana geldiğinde bilindiğinden girdi olarak kullanılmaları **data leakage (veri sızıntısı)** oluşturabilir.

## Altı model

| Model | Nasıl çalışır? | Avantaj | Dezavantaj | Kullanım örneği |
| --- | --- | --- | --- | --- |
| Dummy Classifier | Gözlenen sınıf oranlarını skor olarak kullanır ve çoğunluk sınıfını tahmin eder. | Modeller için kolay anlaşılır bir referans sunar. | Sensörleri kullanmadığı için arızaları ayırt edemez. | Bir arıza uyarı modelinin öğrenme sağladığını kontrol etmek. |
| Logistic Regression | Girdilerin ağırlıklı toplamından bir arıza olasılığı hesaplar. | Hızlıdır ve katsayıları incelenebilir. | Karmaşık sensör etkileşimlerini doğrudan yakalamakta zorlanır. | Açıklanabilir bir ilk risk tahmini geliştirmek. |
| Decision Tree | Sensör eşikleriyle art arda dallanarak bir tahmine ulaşır. | Karar kuralları izlenebilir ve doğrusal olmayan ilişkileri yakalar. | Derin ağaçlar eğitim örneklerine aşırı uyum gösterebilir. | Arızayla ilişkili eşik ve kombinasyonları keşfetmek. |
| Random Forest | Farklı örneklerle eğitilen birçok ağacın tahminlerini birleştirir. | Tek ağaca göre genellikle daha kararlı sonuç üretir. | Eğitim maliyeti artar ve kararları özetlemek zorlaşır. | Tablo biçimindeki sensör verisinde karmaşık ilişkileri modellemek. |
| SVM | Sınıflar arasında geniş bir karar marjı arar. RBF çekirdeği eğri sınırlar oluşturabilir. | Orta büyüklükteki veride doğrusal olmayan ayrımları yakalayabilir. | Ölçeklemeye duyarlıdır ve veri büyüdükçe eğitimi yavaşlayabilir. | Birbirine karışan normal ve arızalı çalışma bölgelerini ayırmak. |
| XGBoost | Yeni ağaçları sırayla ekleyerek tahmin hatasını azaltır. | Tablo verisindeki değişken etkileşimlerini yakalayabilir. | Ayarları ve tahmin gerekçeleri daha karmaşıktır. | Birden fazla sensörün birlikte etkilediği arıza riskini sıralamak. |

## Eğitim ve model seçimi

- **Baseline Model (referans model)**, öğrenen modellerin anlamlı bir iyileşme sağlayıp sağlamadığını gösterir. Dummy model çoğunluk sınıfını seçtiğinde yüksek Accuracy elde edebilir ve arıza Recall değeri sıfır kalabilir.
- **Class Imbalance (sınıf dengesizliği)**, sınıfların eşit sıklıkta görülmemesidir. Veri setindeki 339 arıza yaklaşık %3,39 oranındadır. Logistic Regression, Decision Tree, Random Forest ve SVM sınıf ağırlıkları kullanır. XGBoost her eğitim katındaki sınıf dağılımından hesaplanan örnek ağırlıklarını kullanır.
- **Cross Validation (çapraz doğrulama)** eğitim kümesini beş tabakalı parçaya böler. Her turda dört parça modeli eğitir, kalan parça doğrular. Katlar altı model için ortaktır. Ölçekleme, kategorik kodlama ve model her turda aynı Pipeline içinde yalnızca ilgili eğitim parçasında öğrenilir.
- **Overfitting (aşırı uyum)**, eğitim örneklerindeki ayrıntıların ezberlenmesidir. Eğitim başarısının çok yüksek, doğrulama başarısının düşük olması buna işaret edebilir. **Underfitting (yetersiz uyum)**, modelin örüntüyü yakalayamamasıdır. Eğitim ve doğrulama başarısı birlikte düşük olabilir.
- **Hyperparameter (hiperparametre)**, eğitim başlamadan seçilen ayardır. Ağaç derinliği ve öğrenme oranı buna örnektir. Bu çalışmada ayarlar sabittir. Model seçimi ortalama Average Precision, eşitlikte ortalama F1 ve ardından model adına göre yapılır.

İlk ayrım `stratify=y` ve `random_state=42` ile %80 eğitim ve %20 test olarak yapılır. Test kümesi model seçimi tamamlanınca açılır. Seçilen Pipeline 8.000 satırın tamamında yeniden eğitilir ve 2.000 test satırında değerlendirilir.

## Metrikleri okuma

- **Confusion Matrix (hata matrisi)** satırlarda gerçek sınıfı, sütunlarda tahmini gösterir. TN doğru normal, FP yanlış alarm, FN kaçırılan arıza, TP yakalanan arızadır. Karşılaştırma CSV’si beş doğrulama katının toplam sayılarını içerir.
- **Accuracy** tüm doğru tahminlerin oranıdır. **Balanced Accuracy** iki sınıfın kendi içindeki doğru tahmin oranlarının ortalamasıdır.
- **Precision (kesinlik)**, verilen arıza alarmlarının ne kadarının gerçek arıza olduğunu gösterir. Düşük precision daha fazla yanlış alarma işaret eder.
- **Recall (duyarlılık)**, gerçek arızaların ne kadarının yakalandığını gösterir. Düşük recall daha fazla arızanın gözden kaçtığını gösterir.
- **F1-Score**, Precision ve Recall’un harmonik ortalamasıdır. İkisinden biri düşükse F1 da düşer.
- **ROC-AUC**, eşikler boyunca doğru pozitif oranını yanlış pozitif oranına karşı gösteren ROC eğrisinin altındaki alandır. Rastgele sıralama yaklaşık 0,5 verir.
- **Precision–Recall Curve**, eşik değiştikçe yakalanan arıza oranı ile alarmların isabeti arasındaki ilişkiyi gösterir. **Average Precision (AP)** bu eğriyi recall’daki artışlarla ağırlıklandırılmış precision değerleriyle özetler. Sabit bir skor için AP arıza oranına eşittir.
- **Eğitim süresi**, Pipeline’ın fit süresidir ve donanıma göre değişebilir.

## Çalıştırma

Mevcut PostgreSQL container’ı sağlıklı durumdayken proje kökünden çalıştırın.

```powershell
.\.venv\Scripts\python.exe -m src.train_models
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

[Notebook](../notebooks/04_machine_learning.ipynb) aynı Python modüllerini kullanır. Çapraz doğrulama [karşılaştırma CSV’sini](../results/model_comparison.csv) ve [karşılaştırma grafiğini](../results/model_comparison.png) üretir. Seçilen model için [test metrikleri](../results/test_metrics.csv), [hata matrisi](../results/confusion_matrix.png), [ROC eğrisi](../results/roc_curve.png) ve [Precision–Recall eğrisi](../results/precision_recall_curve.png) kaydedilir.

AI4I 2020 veri seti sentetiktir. Bu sonuçlar gerçek fabrikalardaki performansı garanti etmez.
