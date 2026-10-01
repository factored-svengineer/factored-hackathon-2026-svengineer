"""Baseline dispute category classifier.

Expected approach: TF-IDF + logistic regression (or keyword rules),
trained/evaluated on complaints.description.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.utils.validation import check_is_fitted


class BaselineClassifier:
    """TF-IDF + logistic-regression classifier for complaint labels.

    Encode category and subcategory together in each label, for example
    ``"Transactions | Unrecognized charge"``.
    """

    def __init__(self) -> None:
        self.pipeline = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        lowercase=True,
                        strip_accents="unicode",
                        ngram_range=(1, 2),
                        sublinear_tf=True,
                    ),
                ),
                ("classifier", LogisticRegression(max_iter=1000, random_state=42)),
            ]
        )

    def fit(self, texts: list[str], labels: list[str]) -> BaselineClassifier:
        _validate_training_data(texts, labels)
        if len(set(labels)) < 2:
            raise ValueError("Training requires at least two distinct labels")
        self.pipeline.fit(texts, labels)
        return self

    def predict(self, texts: list[str]) -> list[str]:
        self._require_fitted()
        _validate_texts(texts)
        return self.pipeline.predict(texts).tolist()

    def predict_proba(self, texts: list[str]) -> list[dict[str, float]]:
        self._require_fitted()
        _validate_texts(texts)
        probabilities = self.pipeline.predict_proba(texts)
        classes = self.pipeline.named_steps["classifier"].classes_
        return [
            {str(label): float(probability) for label, probability in zip(classes, row, strict=True)}
            for row in probabilities
        ]

    def _require_fitted(self) -> None:
        check_is_fitted(self.pipeline)


def _validate_texts(texts: list[str]) -> None:
    if not texts:
        raise ValueError("At least one complaint description is required")
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("Complaint descriptions must be non-empty strings")


def _validate_training_data(texts: list[str], labels: list[str]) -> None:
    _validate_texts(texts)
    if len(texts) != len(labels):
        raise ValueError("texts and labels must contain the same number of items")
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("Labels must be non-empty strings")
