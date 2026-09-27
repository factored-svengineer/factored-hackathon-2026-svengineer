"""Baseline dispute-category classifier for held-out evaluation.

TF-IDF + logistic regression (or keyword rules) trained on complaints.description.
"""

from __future__ import annotations


def train_baseline(texts: list[str], labels: list[str]):
    """Fit TF-IDF + LogisticRegression; return a sklearn Pipeline."""
    raise NotImplementedError("Implement TF-IDF + logistic regression baseline")


def evaluate_baseline(model, texts: list[str], labels: list[str]) -> dict:
    """Run held-out evaluation and return accuracy + per-class precision/recall."""
    raise NotImplementedError("Wire to eval.metrics once model is trained")
