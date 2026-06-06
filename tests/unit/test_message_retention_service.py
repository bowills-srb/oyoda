from app.services.operator.message_retention_service import (
    DEFAULT_RETENTION_POLICY,
    merge_retention_policy,
)


def test_merge_retention_policy_uses_defaults():
    policy = merge_retention_policy({})

    assert policy == DEFAULT_RETENTION_POLICY


def test_merge_retention_policy_clamps_and_orders_windows():
    policy = merge_retention_policy(
        {
            "retention_policy": {
                "active_search_window_days": 200,
                "post_stay_follow_up_days": 1,
                "raw_guest_content_retention_days": 15,
                "pre_booking_record_retention_days": 20,
                "guest_session_shell_retention_days": 60,
                "structured_signal_retention_days": 10,
                "auto_cleanup_enabled": False,
            }
        }
    )

    assert policy["active_search_window_days"] == 90
    assert policy["post_stay_follow_up_days"] == 3
    assert policy["raw_guest_content_retention_days"] == 30
    assert policy["pre_booking_record_retention_days"] == 45
    assert policy["guest_session_shell_retention_days"] == 90
    assert policy["structured_signal_retention_days"] == 90
    assert policy["auto_cleanup_enabled"] is False
    assert policy["preserve_guest_identity"] is True


def test_merge_retention_policy_keeps_longer_windows_above_raw_retention():
    policy = merge_retention_policy(
        {
            "retention_policy": {
                "raw_guest_content_retention_days": 120,
                "pre_booking_record_retention_days": 90,
                "guest_session_shell_retention_days": 100,
                "structured_signal_retention_days": 110,
            }
        }
    )

    assert policy["raw_guest_content_retention_days"] == 120
    assert policy["pre_booking_record_retention_days"] == 120
    assert policy["guest_session_shell_retention_days"] == 120
    assert policy["structured_signal_retention_days"] == 120


def test_merge_retention_policy_can_disable_identity_preservation():
    policy = merge_retention_policy(
        {
            "retention_policy": {
                "preserve_guest_identity": False,
            }
        }
    )

    assert policy["preserve_guest_identity"] is False
