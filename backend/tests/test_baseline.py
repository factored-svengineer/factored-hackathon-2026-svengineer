import pytest
from sklearn.exceptions import NotFittedError

from app.classifier.baseline import BaselineClassifier


def test_baseline_classifier_predicts_category_and_subcategory():
    model = BaselineClassifier().fit(
        [
            "I do not recognize the charge on my card",
            "A fraudulent purchase appeared on my account",
            "I was charged twice for the service",
            "Duplicate charge on my statement",
        ],
        [
            "Transactions | Unrecognized charge",
            "Transactions | Unrecognized charge",
            "Fees | Duplicate charge",
            "Fees | Duplicate charge",
        ],
    )

    assert model.predict(["I do not recognize a card charge"])[0] == (
        "Transactions | Unrecognized charge"
    )
    probabilities = model.predict_proba(["I do not recognize a card charge"])[0]
    assert set(probabilities) == {
        "Transactions | Unrecognized charge",
        "Fees | Duplicate charge",
    }
    assert sum(probabilities.values()) == pytest.approx(1.0)


def test_baseline_classifier_rejects_single_class_training_data():
    with pytest.raises(ValueError, match="two distinct labels"):
        BaselineClassifier().fit(["Unrecognized charge"], ["Transactions | Fraud"])


def test_baseline_classifier_requires_fit_before_prediction():
    with pytest.raises(NotFittedError):
        BaselineClassifier().predict(["I do not recognize the charge"])