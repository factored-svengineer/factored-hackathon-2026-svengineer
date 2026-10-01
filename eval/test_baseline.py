import pytest

from eval.baseline import evaluate_baseline, train_baseline


def test_baseline_train_and_held_out_evaluation_report_class_metrics():
    model = train_baseline(
        ["Unrecognized card charge", "Duplicate service payment"],
        ["Transactions | Fraud", "Fees | Duplicate charge"],
    )
    report = evaluate_baseline(
        model,
        ["Unrecognized charge on my card", "The service charged me twice"],
        ["Transactions | Fraud", "Fees | Duplicate charge"],
    )

    assert report["accuracy"] == 1.0
    assert report["per_class"]["Transactions | Fraud"]["recall"] == 1.0


def test_evaluation_rejects_mismatched_text_and_label_counts():
    with pytest.raises(ValueError, match="same number"):
        evaluate_baseline(object(), ["A complaint"], [])