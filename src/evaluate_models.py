"""Compute binary classification metrics and write evaluation artifacts."""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    PrecisionRecallDisplay,
    RocCurveDisplay,
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

METRICS = (
    "accuracy", "balanced_accuracy", "precision", "recall", "f1",
    "roc_auc", "average_precision",
)
METRIC_LABELS = (
    "Accuracy", "Balanced Accuracy", "Precision", "Recall", "F1",
    "ROC-AUC", "Average Precision",
)
RESULTS = Path(__file__).resolve().parents[1] / "results"


def evaluate(model, X, y):
    predictions = model.predict(X)
    if hasattr(model, "decision_function"):
        scores = model.decision_function(X)
    else:
        scores = model.predict_proba(X)[:, 1]
    metrics, matrix = classification_metrics(y, predictions, scores)
    return metrics, matrix, scores


def classification_metrics(y, predictions, scores):
    matrix = confusion_matrix(y, predictions, labels=[0, 1])
    tn, fp, fn, tp = map(int, matrix.ravel())
    metrics = {
        "accuracy": accuracy_score(y, predictions),
        "balanced_accuracy": balanced_accuracy_score(y, predictions),
        "precision": precision_score(y, predictions, zero_division=0),
        "recall": recall_score(y, predictions, zero_division=0),
        "f1": f1_score(y, predictions, zero_division=0),
        "roc_auc": roc_auc_score(y, scores),
        "average_precision": average_precision_score(y, scores),
        "tn": tn, "fp": fp, "fn": fn, "tp": tp,
    }
    return metrics, matrix


def save_results(comparison, winner, test_metrics, matrix, y_test, scores, output=RESULTS):
    output.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output / "model_comparison.csv", index=False, float_format="%.8f")
    pd.DataFrame([{"model": winner, **test_metrics}]).to_csv(
        output / "test_metrics.csv", index=False, float_format="%.8f"
    )

    chart = comparison.set_index("model")
    fig, axes = plt.subplots(2, 4, figsize=(18, 8), layout="constrained")
    for ax, metric, label in zip(
        axes.flat, (*METRICS, "fit_seconds"), (*METRIC_LABELS, "Eğitim süresi (sn)")
    ):
        ax.barh(chart.index, chart[f"{metric}_mean"],
                xerr=chart[f"{metric}_std"], color="#317A8B", capsize=3)
        ax.invert_yaxis()
        ax.set_title(label)
    fig.suptitle("5 katlı çapraz doğrulama · Ortalama ve standart sapma")
    fig.savefig(output / "model_comparison.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(layout="constrained")
    ConfusionMatrixDisplay(matrix, display_labels=["Normal", "Arıza"]).plot(
        ax=ax, cmap="Blues", colorbar=False
    )
    ax.set(xlabel="Tahmin", ylabel="Gerçek", title=f"Test hata matrisi · {winner}")
    fig.savefig(output / "confusion_matrix.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(layout="constrained")
    RocCurveDisplay.from_predictions(y_test, scores, name=winner, ax=ax)
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Rastgele sıralama")
    ax.set(xlabel="Yanlış pozitif oranı", ylabel="Doğru pozitif oranı",
           title=f"Test ROC eğrisi · {winner}")
    ax.legend()
    fig.savefig(output / "roc_curve.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(layout="constrained")
    PrecisionRecallDisplay.from_predictions(y_test, scores, name=winner, ax=ax)
    ax.axhline(y_test.mean(), linestyle="--", color="gray", label="Test arıza oranı")
    ax.set(xlabel="Recall (duyarlılık)", ylabel="Precision (kesinlik)",
           title=f"Test Precision–Recall eğrisi · {winner}")
    ax.legend()
    fig.savefig(output / "precision_recall_curve.png", dpi=150)
    plt.close(fig)
