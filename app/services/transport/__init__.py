"""Channel-agnostic transport layer for guest messaging.

See `base.py` for the core contract.

PHASE 1 STATE (current)
-----------------------
- `GmailTransport` is the only registered provider.
- Credential resolution is DB-backed only via `SqlOperatorCredentialStore`
  (`operator_gmail_creds` table).
- Operators whose inbox credentials live only in legacy environment
  variables are NOT instantiable through this layer yet and continue to
  flow through `app.services.messaging.inbox_adapters`.
- No live runtime callers use this layer yet. Phase 1 is purely additive.

PHASE 2 PLAN
------------
- Rewrite `inbox_adapters.build_inbox_adapter()` and
  `inbox_adapters.build_reply_adapter()` to delegate internally to
  `ChannelTransportFactory`.
- Existing callers in `operator_prebooking.py`, `operator_app.py`,
  `workers/tasks.py`, and `main.py` should remain unchanged during that
  compatibility phase.

PHASE 3+ PLAN
-------------
- Migrate direct callers from `inbox_adapters` to `ChannelTransportFactory`,
  one caller per commit.
- Once no callers import `inbox_adapters`, delete the shim.
"""

from app.services.transport.base import (
    Attachment,
    ChannelTransport,
    MessageDirection,
    NormalizedMessage,
    NormalizedParty,
    NotSupportedError,
    TransportCapability,
)
from app.services.transport.credentials import (
    OperatorCredentialRecord,
    OperatorCredentialStore,
    SqlOperatorCredentialStore,
)
from app.services.transport.factory import (
    ChannelTransportFactory,
    MissingTransportCredentialsError,
    UnknownTransportProviderError,
)
from app.services.transport.providers.gmail_transport import GmailTransport


ChannelTransportFactory.register("gmail", GmailTransport.from_credential_record)
ChannelTransportFactory.register("google", GmailTransport.from_credential_record)


__all__ = [
    "Attachment",
    "ChannelTransport",
    "ChannelTransportFactory",
    "GmailTransport",
    "MessageDirection",
    "MissingTransportCredentialsError",
    "NormalizedMessage",
    "NormalizedParty",
    "NotSupportedError",
    "OperatorCredentialRecord",
    "OperatorCredentialStore",
    "SqlOperatorCredentialStore",
    "TransportCapability",
    "UnknownTransportProviderError",
]
