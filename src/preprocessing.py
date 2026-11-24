"""AI4I verisi için eğitim odaklı, yeniden kullanılabilir ön işleme."""

from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET = "Machine failure"
EXCLUDED_COLUMNS = ["UDI", "Product ID", "TWF", "HDF", "PWF", "OSF", "RNF"]
NUMERIC_FEATURES = [
    "Air temperature [K]", "Process temperature [K]", "Rotational speed [rpm]",
    "Torque [Nm]", "Tool wear [min]",
]
CATEGORICAL_FEATURES = ["Type"]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES


def load_data(path: str | Path) -> pd.DataFrame:
    """Ham CSV dosyasını değiştirmeden oku."""
    return pd.read_csv(path)


def select_features(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Beklenen şemayı doğrula; izin verilen girdiler ile hedefi ayır."""
    required = FEATURES + EXCLUDED_COLUMNS + [TARGET]
    missing_columns = [column for column in required if column not in data.columns]
    if missing_columns:
        raise ValueError(f"Eksik sütunlar: {missing_columns}")
    if data[FEATURES + [TARGET]].isna().any().any():
        raise ValueError("Girdi veya hedef sütunlarında eksik değer var.")
    if any(not pd.api.types.is_numeric_dtype(data[c]) for c in NUMERIC_FEATURES):
        raise ValueError("Sensör sütunları sayısal olmalıdır.")
    if not set(data[TARGET].unique()).issubset({0, 1}) or data[TARGET].nunique() != 2:
        raise ValueError("Hedef hem 0 hem de 1 sınıfını içermelidir.")
    return data[FEATURES].copy(), data[TARGET].copy()


def split_data(X: pd.DataFrame, y: pd.Series):
    """Sınıf oranlarını koruyarak %80 eğitim ve %20 test kümesi oluştur."""
    return train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)


def create_preprocessing_pipeline() -> Pipeline:
    """Henüz fit edilmemiş dönüştürücüyü oluştur."""
    transformer = ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
    return Pipeline([("preprocessor", transformer)])
