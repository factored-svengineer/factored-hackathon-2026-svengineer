"""Evaluation metrics for dispute classification and triage quality."""

from __future__ import annotations

from collections import Counter
from typing import Iterable


def accuracy(y_true: Iterable[str], y_pred: Iterable[str]) -> float:
    yt, yp = list(y_true), list(y_pred)
    if not yt:
        return 0.0
    return sum(a == b for a, b in zip(yt, yp)) / len(yt)


def precision_recall_by_label(
    y_true: Iterable[str], y_pred: Iterable[str]
) -> dict[str, dict[str, float]]:
    yt, yp = list(y_true), list(y_pred)
    labels = sorted(set(yt) | set(yp))
    true_pos: Counter[str] = Counter()
    pred_pos: Counter[str] = Counter()
    actual_pos: Counter[str] = Counter()

    for t, p in zip(yt, yp):
        actual_pos[t] += 1
        pred_pos[p] += 1
        if t == p:
            true_pos[t] += 1

    out: dict[str, dict[str, float]] = {}
    for label in labels:
        prec = true_pos[label] / pred_pos[label] if pred_pos[label] else 0.0
        rec = true_pos[label] / actual_pos[label] if actual_pos[label] else 0.0
        out[label] = {"precision": prec, "recall": rec, "support": float(actual_pos[label])}
    return out
