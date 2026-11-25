"""Compare a fixed CPU MLP with classical classifiers on shared training folds."""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import PrecisionRecallDisplay, RocCurveDisplay
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from src.evaluate_models import METRICS, METRIC_LABELS, RESULTS, classification_metrics
from src.mlp_model import FailureMLP
from src.preprocessing import create_preprocessing_pipeline, split_data
from src.train_models import build_models, compare_models, load_training_data, training_folds

SEED = 42
EPOCHS = 50
BATCH_SIZE = 64
LEARNING_RATE = 0.001
THRESHOLD = 0.5
OUTPUT = RESULTS / "mlp"


def prepare_fold(X_fit, X_validation):
    preprocessor = create_preprocessing_pipeline()
    train = preprocessor.fit_transform(X_fit)
    validation = preprocessor.transform(X_validation)
    tensors = []
    for values in (train, validation):
        if hasattr(values, "toarray"):
            values = values.toarray()
        if values.shape[1] != FailureMLP.INPUT_SIZE:
            raise ValueError("MLP için 8 dönüştürülmüş özellik bekleniyor.")
        tensors.append(torch.as_tensor(values, dtype=torch.float32))
    return (*tensors, preprocessor)


def positive_weight(y_fit):
    positives = int(y_fit.sum())
    negatives = len(y_fit) - positives
    if not positives or not negatives:
        raise ValueError("Eğitim katında her iki sınıf da bulunmalıdır.")
    return negatives / positives


def fit_fold(X_fit, y_fit, X_validation, y_validation, *, seed):
    train, validation, _ = prepare_fold(X_fit, X_validation)
    labels = torch.tensor(y_fit.to_numpy(), dtype=torch.float32)
    weight = positive_weight(y_fit)
    batches = DataLoader(
        TensorDataset(train, labels), batch_size=BATCH_SIZE, shuffle=True,
        generator=torch.Generator().manual_seed(seed),
    )
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = FailureMLP()
    loss_function = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(weight))
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    history = []

    for epoch in range(1, EPOCHS + 1):
        model.train()
        total_loss = 0.0
        for features, target in batches:
            optimizer.zero_grad()
            loss = loss_function(model(features), target)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(target)

        model.eval()
        with torch.inference_mode():
            scores = torch.sigmoid(model(validation)).numpy()
        metrics, _ = classification_metrics(y_validation, scores >= THRESHOLD, scores)
        history.append({"epoch": epoch, "train_loss": total_loss / len(labels), **metrics})

    return history, scores, weight


def cross_validate_mlp(X_train, y_train):
    history_rows, fold_rows = [], []
    oof = np.full(len(y_train), np.nan)
    previous_threads = torch.get_num_threads()
    # Small batches run faster on a single CPU thread.
    torch.set_num_threads(1)
    try:
        for fold, (fit, validation) in enumerate(training_folds(X_train, y_train), start=1):
            history, scores, weight = fit_fold(
                X_train.iloc[fit], y_train.iloc[fit],
                X_train.iloc[validation], y_train.iloc[validation],
                seed=SEED + fold - 1,
            )
            history_rows.extend({"fold": fold, **row} for row in history)
            fold_rows.append({
                "fold": fold, "epoch": EPOCHS, "pos_weight": weight,
                **{metric: history[-1][metric] for metric in METRICS},
            })
            oof[validation] = scores
    finally:
        torch.set_num_threads(previous_threads)
    if not np.isfinite(oof).all():
        raise ValueError("Her eğitim satırı için bir doğrulama skoru bekleniyordu.")
    return pd.DataFrame(fold_rows), pd.DataFrame(history_rows), oof


def compare_with_classical(X_train, y_train, folds):
    columns = [f"{metric}_{stat}" for metric in METRICS for stat in ("mean", "std")]
    classical = compare_models(build_models(), X_train, y_train)[["model", *columns]]
    mlp = {"model": "MLP"}
    for metric in METRICS:
        mlp[f"{metric}_mean"] = folds[metric].mean()
        mlp[f"{metric}_std"] = folds[metric].std()
    return pd.concat([classical, pd.DataFrame([mlp])], ignore_index=True).sort_values(
        ["average_precision_mean", "f1_mean", "model"], ascending=[False, False, True]
    ).reset_index(drop=True)


def save_figure(fig, path):
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_results(folds, history, comparison, y_train, oof, output=OUTPUT):
    output.mkdir(parents=True, exist_ok=True)
    folds.to_csv(output.parent / "mlp_metrics.csv", index=False, float_format="%.8f")
    comparison.to_csv(output / "model_comparison.csv", index=False, float_format="%.8f")
    history.to_csv(output / "training_history.csv", index=False, float_format="%.8f")

    fig, ax = plt.subplots(figsize=(9, 2.5), layout="constrained")
    ax.set(xlim=(0, 1), ylim=(0, 1), title="Arıza tahmini için MLP mimarisi")
    ax.axis("off")
    layers = [
        "Girdi\n8 özellik", "Gizli katman\n32 nöron · ReLU",
        "Gizli katman\n16 nöron · ReLU", "Çıktı\n1 ham logit",
    ]
    positions = (0.10, 0.36, 0.64, 0.90)
    for position, label in zip(positions, layers):
        ax.text(position, 0.55, label, ha="center", va="center",
                bbox={"boxstyle": "round,pad=0.55", "fc": "#E0F0F1", "ec": "#317A8B"})
    for left, right in zip(positions, positions[1:]):
        ax.annotate("", (right - 0.09, 0.55), (left + 0.09, 0.55),
                    arrowprops={"arrowstyle": "->", "color": "#245464"})
    ax.text(0.5, 0.14, "Çıktı logiti → Sigmoid → arıza skoru", ha="center")
    save_figure(fig, output / "architecture.png")

    for column, ylabel, filename in (
        ("train_loss", "Ağırlıklı BCE kaybı", "training_loss.png"),
        ("average_precision", "Doğrulama Average Precision", "validation_performance.png"),
    ):
        fig, ax = plt.subplots(layout="constrained")
        for fold, rows in history.groupby("fold"):
            ax.plot(rows["epoch"], rows[column], alpha=0.65, label=f"Kat {fold}")
        mean = history.groupby("epoch")[column].mean()
        ax.plot(mean.index, mean, color="black", linewidth=2, label="Ortalama")
        ax.set(xlabel="Epoch", ylabel=ylabel)
        ax.legend(ncols=2)
        save_figure(fig, output / filename)

    fig, ax = plt.subplots(layout="constrained")
    RocCurveDisplay.from_predictions(y_train, oof, name="MLP", ax=ax)
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Rastgele sıralama")
    ax.set(xlabel="Yanlış pozitif oranı", ylabel="Doğru pozitif oranı",
           title="ROC · beş doğrulama katının birleşik tahminleri")
    ax.legend()
    save_figure(fig, output / "roc_curve.png")

    fig, ax = plt.subplots(layout="constrained")
    PrecisionRecallDisplay.from_predictions(y_train, oof, name="MLP", ax=ax)
    ax.axhline(y_train.mean(), linestyle="--", color="gray", label="Arıza oranı")
    ax.set(xlabel="Recall (duyarlılık)", ylabel="Precision (kesinlik)",
           title="Precision–Recall · birleşik doğrulama tahminleri")
    ax.legend()
    save_figure(fig, output / "precision_recall_curve.png")

    fig, axes = plt.subplots(2, 4, figsize=(16, 8), layout="constrained")
    for ax, metric, title in zip(axes.flat, METRICS, METRIC_LABELS):
        colors = ["#B64D30" if name == "MLP" else "#317A8B" for name in comparison["model"]]
        ax.barh(comparison["model"], comparison[f"{metric}_mean"], color=colors,
                xerr=comparison[f"{metric}_std"], capsize=3)
        ax.invert_yaxis()
        ax.set(xlim=(0, 1.03), title=title)
    axes.flat[-1].axis("off")
    fig.suptitle("Yedi model · 5 katlı doğrulama ortalaması ve standart sapma")
    save_figure(fig, output / "model_comparison.png")


def load_development_data():
    X, y = load_training_data()
    X_train, _, y_train, _ = split_data(X, y)
    return X_train, y_train


def main():
    X_train, y_train = load_development_data()
    folds, history, oof = cross_validate_mlp(X_train, y_train)
    comparison = compare_with_classical(X_train, y_train, folds)
    save_results(folds, history, comparison, y_train, oof)
    print(comparison[["model", "average_precision_mean"]].to_string(index=False))


if __name__ == "__main__":
    main()
