"""Download the original AI4I CSV from the UCI archive and inspect it."""

import argparse
import io
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import pandas as pd


DATASET_URL = (
    "https://archive.ics.uci.edu/static/public/601/"
    "ai4i%2B2020%2Bpredictive%2Bmaintenance%2Bdataset.zip"
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "raw" / "ai4i2020.csv"


def download_dataset(destination: Path) -> None:
    """Extract the CSV bytes without changing their contents."""
    with urlopen(DATASET_URL, timeout=60) as response:
        archive_bytes = response.read()
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        csv_bytes = archive.read("ai4i2020.csv")

    # Validate the downloaded content before replacing any existing file.
    frame = pd.read_csv(io.BytesIO(csv_bytes))
    if frame.empty or "Machine failure" not in frame.columns:
        raise ValueError("Downloaded CSV does not have the expected structure.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(csv_bytes)


def report_dataset(path: Path) -> None:
    """Print a concise inspection without modifying the source file."""
    frame = pd.read_csv(path)
    print(f"Satır sayısı: {len(frame)}; sütun sayısı: {len(frame.columns)}")
    print("\nSütunlar:")
    print("\n".join(frame.columns))
    print("\nİlk 5 kayıt:")
    print(frame.head().to_string(index=False))
    print("\nSütunlara göre eksik veri sayısı:")
    print(frame.isna().sum().to_string())
    print(f"Toplam eksik veri: {frame.isna().sum().sum()}")
    print("\nMachine failure sınıf dağılımı:")
    print(frame["Machine failure"].value_counts(dropna=False).sort_index().to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Download again even if the CSV exists."
    )
    args = parser.parse_args()
    if CSV_PATH.exists() and not args.force:
        print(f"Mevcut dosya kullanılıyor: {CSV_PATH}")
    else:
        download_dataset(CSV_PATH)
        print(f"Veri indirildi: {CSV_PATH}")
    report_dataset(CSV_PATH)


if __name__ == "__main__":
    main()
