"""Compare current unlabeled sensor events with the model training reference."""

import argparse
import json

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from src.database import connect
from src.preprocessing import FEATURES, NUMERIC_FEATURES, split_data
from src.train_models import load_training_data

MIN_VALID = 30
KS_THRESHOLD = 0.20
TV_THRESHOLD = 0.15
PRODUCT_TYPES = ("H", "L", "M")


def load_monitoring_data(limit=1000):
    if not 1 <= limit <= 10_000:
        raise ValueError("Akış örnek sınırı 1–10.000 arasında olmalıdır.")
    features, labels = load_training_data()
    reference, _, _, _ = split_data(features, labels)
    with connect() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        rows = connection.execute("""
            SELECT product_type, air_temperature, process_temperature, rotational_speed, torque, tool_wear
            FROM public.stream_sensor_readings
            ORDER BY event_time DESC, event_id DESC LIMIT %s
        """, (limit,)).fetchall()
    return reference, pd.DataFrame.from_records(rows, columns=FEATURES)


def compare_distributions(reference, stream):
    checks = []
    for column in NUMERIC_FEATURES:
        expected = reference[column].to_numpy(dtype=float)
        observed = pd.to_numeric(stream[column], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        finite = np.isfinite(observed)
        domain = observed > 0 if column in NUMERIC_FEATURES[:2] else observed >= 0
        if column in (NUMERIC_FEATURES[2], NUMERIC_FEATURES[4]):
            domain &= observed == np.trunc(observed)
        clean = observed[finite & domain]
        score = float(ks_2samp(expected, clean).statistic) if len(clean) >= MIN_VALID else None
        checks.append({
            "feature": column, "method": "KS statistic", "threshold": KS_THRESHOLD,
            "score": score, "status": assess(score, KS_THRESHOLD),
            "missing_or_nonfinite": int((~finite).sum()),
            "out_of_domain": int((finite & ~domain).sum()),
            "outside_reference_range": int(((clean < expected.min()) | (clean > expected.max())).sum()),
            "valid_stream_rows": len(clean),
        })
    categories = stream["Type"]
    valid = categories.isin(PRODUCT_TYPES)
    observed = categories[valid]
    proportions = observed.value_counts(normalize=True).reindex(PRODUCT_TYPES, fill_value=0)
    baseline = reference["Type"].value_counts(normalize=True).reindex(PRODUCT_TYPES, fill_value=0)
    score = float((proportions - baseline).abs().sum() / 2) if len(observed) >= MIN_VALID else None
    checks.append({
        "feature": "Type", "method": "Total variation", "threshold": TV_THRESHOLD,
        "score": score, "status": assess(score, TV_THRESHOLD),
        "missing_or_nonfinite": int(categories.isna().sum()),
        "out_of_domain": int((categories.notna() & ~valid).sum()),
        "outside_reference_range": None, "valid_stream_rows": len(observed),
    })
    return {"reference_rows": len(reference), "stream_rows": len(stream), "features": checks}


def assess(score, threshold):
    if score is None:
        return "insufficient_data"
    return "review" if score >= threshold else "below_threshold"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(compare_distributions(*load_monitoring_data(args.limit)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
