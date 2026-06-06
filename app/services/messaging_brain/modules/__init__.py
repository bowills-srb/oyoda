"""
Modules — operational work handlers for the messaging brain.

Modules own the WORK. Agents own the DECISION. The brain dispatches
ModuleEvents from agent decisions to the registered module that handles
that event's module key.

Phase 1.3 modules:
  - MaintenanceModule (maintenance_module.py): writes both
    concierge_maintenance_events and operator_work_orders, with explicit
    linking. Operator-only routing for now; vendor routing plugs in
    later without changing the brain.

See docs/PHASE_1_3_SEAM_MAP.md "Architectural design rules" for the
ownership constraints these modules must satisfy.
"""

from app.services.messaging_brain.modules.base import (
    BaseOyvodaModule,
    ModuleRegistry,
)
from app.services.messaging_brain.modules.maintenance_module import (
    MaintenanceModule,
)

__all__ = [
    "BaseOyvodaModule",
    "ModuleRegistry",
    "MaintenanceModule",
]
