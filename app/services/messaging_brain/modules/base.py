"""
base.py — Module protocol and registry for the messaging brain.

A Module is the WORK side of the agent/module split. Agents emit
ModuleEvents from their decisions; the orchestrator dispatches each event
to the registered module identified by ModuleEvent.module.

Protocol contract:
  - .name: stable string identifier (e.g. "MaintenanceModule")
  - .handles_event_types: tuple of event_type strings this module accepts
  - async .handle_event(event, *, db_session, shadow_mode) -> ModuleResponse

Shadow mode contract:
  Modules MUST respect the shadow_mode flag. When shadow_mode is True,
  the module performs all classification and structured response work
  but skips side-effecting writes (work order creation, vendor
  notification, etc.). The returned ModuleResponse should populate
  result["shadow"] = True and describe what would have happened.
  See docs/PHASE_1_3_SEAM_MAP.md "Rule 5".

Registry:
  The orchestrator owns one ModuleRegistry instance. Modules register
  themselves at orchestrator construction time. Registry lookup is by
  module key (e.g. "maintenance"), which matches ModuleEvent.module.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol, runtime_checkable

from app.services.orchestration.messaging_brain_contracts import (
    ModuleEvent,
    ModuleResponse,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class BaseOyvodaModule(Protocol):
    """Protocol every module must satisfy.

    Structurally typed — no inheritance required. Implement the four
    members and the registry will accept it.
    """

    name: str
    handles_event_types: tuple[str, ...]

    async def handle_event(
        self,
        event: ModuleEvent,
        *,
        db_session: Any,
        shadow_mode: bool = False,
    ) -> ModuleResponse:
        ...


class ModuleRegistry:
    """Maps module key (e.g. "maintenance") to module instance.

    The orchestrator constructs one of these and registers all modules
    at startup. Lookup is by ModuleEvent.module.

    Stateless lookups; not thread-safe for concurrent registration but
    that doesn't happen in production (modules register at construction).
    """

    def __init__(self) -> None:
        self._modules: dict[str, BaseOyvodaModule] = {}

    def register(self, module_key: str, module: BaseOyvodaModule) -> None:
        """Register a module under module_key.

        module_key matches ModuleEvent.module (e.g. "maintenance",
        "housekeeping"). Re-registering the same key replaces the
        previous module — useful for tests, logged at WARNING in prod.
        """
        if not isinstance(module, BaseOyvodaModule):
            raise TypeError(
                f"module {module!r} does not satisfy BaseOyvodaModule protocol "
                f"(needs .name, .handles_event_types, async .handle_event)"
            )
        if module_key in self._modules:
            logger.warning(
                "[ModuleRegistry] re-registering %s (was %r, now %r)",
                module_key, self._modules[module_key], module,
            )
        self._modules[module_key] = module
        logger.info(
            "[ModuleRegistry] registered %s as %r (handles: %s)",
            module_key, module.name, module.handles_event_types,
        )

    def get(self, module_key: str) -> Optional[BaseOyvodaModule]:
        """Return the registered module, or None if not registered."""
        return self._modules.get(module_key)

    def keys(self) -> list[str]:
        """All registered module keys, sorted. For tests + introspection."""
        return sorted(self._modules.keys())
