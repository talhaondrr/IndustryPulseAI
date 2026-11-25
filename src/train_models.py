"""Load the training view and compare classifiers on training folds."""

from time import perf_counter

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

from src.database import connect
from src.evaluate_models import METRICS, evaluate
from src.preprocessing import FEATURES, TARGET, create_preprocessing_pipeline, select_features, split_data

TRAINING_QUERY = """
SELECT type_code, air_temperature, process_temperature, rotational_speed,
       torque, tool_wear, machine_failure
FROM public.ml_training_data
ORDER BY type_code COLLATE "C", air_temperature, process_temperature,
         rotational_speed, torque, tool_wear, machine_failure
"""


def load_training_data():
    with connect() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        rows = connection.execute(TRAINING_QUERY).fetchall()
    if len(rows) != 10_000:
        raise ValueError(f"10.000 kayıt bekleniyordu, {len(rows)} kayıt geldi.")

    data = pd.DataFrame.from_records(rows, columns=FEATURES + [TARGET], coerce_float=True)
    if not np.isfinite(data[FEATURES[1:]].to_numpy(dtype=float)).all():
        raise ValueError("Sensör ölçümleri sonlu olmalıdır.")
    return select_features(data, from_training_view=True)


def build_models():
    estimators = {
        "Dummy Classifier": DummyClassifier(strategy="prior", random_state=42),
        "Logistic Regression": LogisticRegression(class_weight="balanced", max_iter=2000),
        "Decision Tree": DecisionTreeClassifier(class_weight="balanced", random_state=42),
        "Random Forest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced_subsample", random_state=42, n_jobs=1
        ),
        "SVM": SVC(kernel="rbf", class_weight="balanced", cache_size=512),
        "XGBoost": XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            eval_metric="logloss", random_state=42, n_jobs=1, tree_method="hist",
        ),
    }
    return {
        name: Pipeline(create_preprocessing_pipeline().steps + [("classifier", estimator)])
        for name, estimator in estimators.items()
    }


def fit_model(pipeline, X, y):
    fitted = clone(pipeline)
    fit_params = {}
    if isinstance(fitted.named_steps["classifier"], XGBClassifier):
        fit_params["classifier__sample_weight"] = compute_sample_weight("balanced", y)
    started = perf_counter()
    fitted.fit(X, y, **fit_params)
    return fitted, perf_counter() - started


def training_folds(X_train, y_train):
    splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    return list(splitter.split(X_train, y_train))


def compare_models(models, X_train, y_train):
    splits = training_folds(X_train, y_train)
    rows = []
    for name, pipeline in models.items():
        fold_rows = []
        for fit_indices, validation_indices in splits:
            fitted, fit_seconds = fit_model(
                pipeline, X_train.iloc[fit_indices], y_train.iloc[fit_indices]
            )
            metrics, _, _ = evaluate(
                fitted, X_train.iloc[validation_indices], y_train.iloc[validation_indices]
            )
            fold_rows.append({**metrics, "fit_seconds": fit_seconds})
        folds = pd.DataFrame(fold_rows)
        row = {"model": name}
        for column in (*METRICS, "fit_seconds"):
            row[f"{column}_mean"] = folds[column].mean()
            row[f"{column}_std"] = folds[column].std()
        for column in ("tn", "fp", "fn", "tp"):
            row[column] = int(folds[column].sum())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["average_precision_mean", "f1_mean", "model"], ascending=[False, False, True]
    ).reset_index(drop=True)


def main():
    from src.evaluate_models import save_results

    X, y = load_training_data()
    X_train, X_test, y_train, y_test = split_data(X, y)
    models = build_models()
    comparison = compare_models(models, X_train, y_train)
    winner = comparison.iloc[0]["model"]
    model, fit_seconds = fit_model(models[winner], X_train, y_train)
    test_metrics, matrix, scores = evaluate(model, X_test, y_test)
    save_results(comparison, winner, {**test_metrics, "fit_seconds": fit_seconds},
                 matrix, y_test, scores)
    print(comparison.to_string(index=False))
    print(winner, test_metrics)


if __name__ == "__main__":
    main()
