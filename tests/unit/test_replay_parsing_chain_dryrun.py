from types import SimpleNamespace
import sys


class _FakeCeleryApp:
    def __init__(self, *args, **kwargs):
        self.conf = SimpleNamespace(update=lambda *a, **k: None)

    def task(self, *args, **kwargs):
        def _decorator(fn):
            return fn

        return _decorator


sys.modules.setdefault(
    "celery",
    SimpleNamespace(Celery=_FakeCeleryApp),
)
sys.modules.setdefault(
    "celery.schedules",
    SimpleNamespace(crontab=lambda *a, **k: ("crontab", a, k)),
)

from app.workers.tasks import (
    _original_looked_like_guest_inquiry,
    _replay_discrepancy_category,
    _replay_route_bucket,
)


def test_replay_route_bucket_non_guest_wins():
    assert _replay_route_bucket("dryrun_llm_route_only_groq", non_guest_reason="subject:marketing_pattern") == "non_guest"


def test_replay_route_bucket_llm_and_booking_event():
    assert _replay_route_bucket("dryrun_llm_route_only_groq") == "llm_route"
    assert _replay_route_bucket("ota_reservation_event_airbnb") == "booking_event"
    assert _replay_route_bucket("ota_parser_vrbo") == "deterministic_ota_parser"
    assert _replay_route_bucket("direct_website_form_parser") == "deterministic_direct_parser"


def test_replay_guest_inquiry_heuristics():
    assert _original_looked_like_guest_inquiry("llm_email_extractor_groq", "")
    assert _original_looked_like_guest_inquiry("generic_gmail_parser", "")
    assert _original_looked_like_guest_inquiry("", "pre_booking_new")
    assert not _original_looked_like_guest_inquiry("ota_reservation_event_airbnb", "")


def test_replay_discrepancy_flags_concerning_route_changes():
    assert (
        _replay_discrepancy_category(
            original_parser_used="llm_email_extractor_groq",
            original_route_outcome="pre_booking_new",
            new_route_bucket="non_guest",
        )
        == "possible_false_positive_non_guest"
    )
    assert (
        _replay_discrepancy_category(
            original_parser_used="generic_gmail_parser",
            original_route_outcome="pre_booking_duplicate",
            new_route_bucket="booking_event",
        )
        == "possible_false_positive_booking_event"
    )
    assert (
        _replay_discrepancy_category(
            original_parser_used="ota_reservation_event_airbnb",
            original_route_outcome="system_event",
            new_route_bucket="booking_event",
        )
        == "none"
    )
