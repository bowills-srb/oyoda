from __future__ import annotations

from app.services.operator.historical_thread_evaluator import HistoricalThreadEvaluator


def test_historical_thread_evaluator_detects_domains_and_builds_review_template():
    evaluator = HistoricalThreadEvaluator()
    text = """
Guest: The AC is broken and there is water on the floor. Can we get a refund?

Host: We are dispatching HVAC now and will update you shortly.

Guest: We are arriving soon and the place still looks dirty.

Host: We are checking on cleaning and turnover status now.
""".strip()

    analysis = evaluator.analyze_text(text, source_name="sample.txt")

    assert analysis["parse_mode"] == "labeled"
    assert analysis["qa_pair_count"] == 2
    assert analysis["domain_counts"]["claims_billing"] >= 1
    assert analysis["domain_counts"]["arrival_turnover"] >= 1

    review = evaluator.build_review_template(analysis)
    assert len(review["review_items"]) == 2
    assert review["review_items"][0]["detected_domain"]
