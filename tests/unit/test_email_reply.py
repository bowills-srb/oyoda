from app.services.integrations.email_reply import EmailReplySenderBase


class _StubReplySender(EmailReplySenderBase):
    pass


def test_rfc2822_email_builder_produces_thread_headers():
    sender = _StubReplySender(token_manager=None)

    rendered = sender._build_rfc2822_email(
        to_address="guest@example.com",
        to_name="Guest",
        subject="Re: Your stay",
        body="Happy to help.",
        in_reply_to="<abc123@example.com>",
        references="<abc123@example.com>",
        from_email="host@example.com",
        from_name="Host Team",
    )

    assert "From: Host Team <host@example.com>" in rendered
    assert "To: Guest <guest@example.com>" in rendered
    assert "Subject: Re: Your stay" in rendered
    assert "In-Reply-To: <abc123@example.com>" in rendered
    assert "References: <abc123@example.com>" in rendered
    assert rendered.endswith("Happy to help.")
