from __future__ import annotations

from typing import Any


class StayOperationsService:
    def evaluate(self, row: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
        phase = str(row.get("phase") or workflow.get("phase") or "").lower()
        policy = ((workflow.get("policy") or {}).get("stay_operations") or {}) if isinstance(workflow.get("policy"), dict) else {}
        profile = str(policy.get("workflow_profile") or "assisted_ops").strip().lower()
        journey = workflow.get("journey") if isinstance(workflow.get("journey"), dict) else {}
        turnover = workflow.get("turnover") if isinstance(workflow.get("turnover"), dict) else {}
        walkthrough = workflow.get("walkthrough") if isinstance(workflow.get("walkthrough"), dict) else {}

        modules = self._modules(policy, profile)

        tasks: list[dict[str, Any]] = []
        if modules["access_workflows"] and phase in {"pre_arrival", "arrival_day"}:
            access_complete = bool(journey.get("welcome_sent") or journey.get("checkin_reminder_sent"))
            tasks.append(
                {
                    "key": "access_readiness",
                    "label": "Arrival access readiness",
                    "required": True,
                    "status": "complete" if access_complete else "pending",
                    "domain": "access",
                }
            )

        if modules["rental_workflows"] and phase in {"pre_arrival", "arrival_day"}:
            tasks.append(
                {
                    "key": "guest_rental_coordination",
                    "label": "Rental / concierge opportunity",
                    "required": False,
                    "status": "opportunity",
                    "domain": "rental",
                }
            )

        if modules["turnover_workflows"] and phase in {"departure_day", "post_stay"}:
            turnover_status = str(turnover.get("status") or "pending").lower()
            if turnover_status in {"ready", "archived"}:
                task_status = "complete"
            elif turnover_status in {"in_progress", "planned"}:
                task_status = "in_progress"
            elif turnover_status in {"failed", "reassigned", "cancelled"}:
                task_status = turnover_status
            else:
                task_status = "pending"
            tasks.append(
                {
                    "key": "housekeeping_turnover",
                    "label": "Housekeeping / turnover",
                    "required": True,
                    "status": task_status,
                    "domain": "turnover",
                }
            )

        if modules["post_checkout_walkthrough"] and phase == "post_stay":
            walkthrough_status = str(walkthrough.get("status") or "pending").lower()
            tasks.append(
                {
                    "key": "post_checkout_walkthrough",
                    "label": "Post-checkout documentation / walkthrough",
                    "required": bool(modules.get("walkthrough_required_before_ready")),
                    "status": walkthrough_status,
                    "domain": "walkthrough",
                }
            )

        next_step = next((task for task in tasks if task["status"] in {"pending", "in_progress", "failed", "reassigned", "cancelled"}), None)
        return {
            "profile": profile,
            "modules": modules,
            "tasks": tasks,
            "next_step": next_step,
            "vendor_domains": [
                domain
                for domain, enabled in (
                    ("access", modules["access_workflows"]),
                    ("rental", modules["rental_workflows"]),
                    ("turnover", modules["turnover_workflows"]),
                    ("maintenance", modules["maintenance_workflows"]),
                    ("walkthrough", modules["post_checkout_walkthrough"]),
                )
                if enabled
            ],
        }

    def _modules(self, policy: dict[str, Any], profile: str) -> dict[str, bool]:
        if profile == "messaging_only":
            defaults = {
                "access_workflows": False,
                "rental_workflows": False,
                "turnover_workflows": False,
                "maintenance_workflows": False,
                "post_checkout_walkthrough": False,
            }
        elif profile == "full_ops":
            defaults = {
                "access_workflows": True,
                "rental_workflows": True,
                "turnover_workflows": True,
                "maintenance_workflows": True,
                "post_checkout_walkthrough": True,
            }
        else:
            defaults = {
                "access_workflows": True,
                "rental_workflows": True,
                "turnover_workflows": True,
                "maintenance_workflows": True,
                "post_checkout_walkthrough": False,
            }
        return {
            "access_workflows": bool(policy.get("enable_access_workflows", defaults["access_workflows"])),
            "rental_workflows": bool(policy.get("enable_rental_workflows", defaults["rental_workflows"])),
            "turnover_workflows": bool(policy.get("enable_turnover_workflows", defaults["turnover_workflows"])),
            "maintenance_workflows": bool(policy.get("enable_maintenance_workflows", defaults["maintenance_workflows"])),
            "post_checkout_walkthrough": bool(policy.get("enable_post_checkout_walkthrough", defaults["post_checkout_walkthrough"])),
            "auto_archive_when_turnover_ready": bool(policy.get("auto_archive_when_turnover_ready", True)),
            "walkthrough_required_before_ready": bool(policy.get("walkthrough_required_before_ready", bool(policy.get("enable_post_checkout_walkthrough", defaults["post_checkout_walkthrough"])))),
        }


_SERVICE = StayOperationsService()


def get_stay_operations_service() -> StayOperationsService:
    return _SERVICE
