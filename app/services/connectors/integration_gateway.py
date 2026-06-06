"""
Integration credential gateway for external operator systems.

This layer now uses a canonical provider contract for PMS platforms so new
operators can connect different systems without forcing schema changes.

Credentials are encrypted at rest in a local file for development.
Production should use a managed secrets store.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.services.connectors.pms_connectors import (
    PMSConnectorFactory,
    PMSProvider,
)


class IntegrationProvider(str, Enum):
    BREEZEWAY = "breezeway"
    ESCAPIA = "escapia"
    GUESTY = "guesty"
    HOSTAWAY = "hostaway"
    STREAMLINE = "streamline"
    LODGIFY = "lodgify"
    TRACK = "track"
    HOSTFULLY = "hostfully"
    OWNERREZ = "ownerrez"
    BEDS24 = "beds24"
    SMOOBU = "smoobu"
    WHEELHOUSE = "wheelhouse"


def _contract_schema(provider: PMSProvider) -> Dict[str, Any]:
    contract = PMSConnectorFactory.get_provider_contract(provider)
    return {
        "name": contract.display_name,
        "auth_scheme": contract.auth_scheme.value,
        "message_transport": contract.message_transport.value,
        "readiness": contract.readiness.value,
        "required_fields": [field.name for field in contract.required_fields],
        "optional_fields": [field.name for field in contract.optional_fields],
        "field_specs": [field.to_dict() for field in contract.required_fields + contract.optional_fields],
        "capabilities": contract.capabilities.to_dict(),
        "notes": contract.notes,
    }


PROVIDER_SCHEMAS: Dict[IntegrationProvider, Dict[str, Any]] = {
    IntegrationProvider.BREEZEWAY: {
        "name": "Breezeway",
        "auth_scheme": "api_key",
        "message_transport": "none",
        "readiness": "implemented",
        "required_fields": ["api_key"],
        "optional_fields": ["provider_account_id", "account_id", "provider_base_url", "client_id", "client_secret"],
        "field_specs": [],
        "capabilities": {},
        "notes": "Operations and maintenance system, not a PMS source of booking truth.",
    },
    IntegrationProvider.ESCAPIA: _contract_schema(PMSProvider.ESCAPIA),
    IntegrationProvider.GUESTY: _contract_schema(PMSProvider.GUESTY),
    IntegrationProvider.HOSTAWAY: _contract_schema(PMSProvider.HOSTAWAY),
    IntegrationProvider.STREAMLINE: _contract_schema(PMSProvider.STREAMLINE),
    IntegrationProvider.LODGIFY: _contract_schema(PMSProvider.LODGIFY),
    IntegrationProvider.TRACK: _contract_schema(PMSProvider.TRACK),
    IntegrationProvider.HOSTFULLY: _contract_schema(PMSProvider.HOSTFULLY),
    IntegrationProvider.OWNERREZ: _contract_schema(PMSProvider.OWNERREZ),
    IntegrationProvider.BEDS24: _contract_schema(PMSProvider.BEDS24),
    IntegrationProvider.SMOOBU: _contract_schema(PMSProvider.SMOOBU),
    IntegrationProvider.WHEELHOUSE: {
        "name": "Wheelhouse",
        "auth_scheme": "api_key",
        "message_transport": "none",
        "readiness": "implemented",
        "required_fields": ["api_key"],
        "optional_fields": ["provider_account_id", "portfolio_id", "provider_base_url", "base_url"],
        "field_specs": [],
        "capabilities": {},
        "notes": "Pricing system, not a PMS source of booking truth.",
    },
}


def _utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


class IntegrationCredentialStore:
    """Encrypted credential store for local development."""

    def __init__(self, storage_file: Path | None = None) -> None:
        settings = get_settings()
        if storage_file is None:
            storage_file = Path("/tmp/rentalrevenue_gateway_credentials.enc")
        self._storage_file = storage_file
        self._fernet = Fernet(self._build_fernet_key(settings.secret_key))

    @staticmethod
    def _build_fernet_key(secret: str) -> bytes:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    def _load(self) -> Dict[str, Any]:
        if not self._storage_file.exists():
            return {"version": 1, "companies": {}}
        encrypted = self._storage_file.read_bytes()
        try:
            payload = self._fernet.decrypt(encrypted)
        except InvalidToken:
            raise ValueError("Credential vault could not be decrypted with current SECRET_KEY")
        return json.loads(payload.decode("utf-8"))

    def _save(self, data: Dict[str, Any]) -> None:
        self._storage_file.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encrypted = self._fernet.encrypt(encoded)
        self._storage_file.write_bytes(encrypted)

    def get_supported_providers(self) -> List[Dict[str, Any]]:
        providers: List[Dict[str, Any]] = []
        for provider, schema in PROVIDER_SCHEMAS.items():
            providers.append(
                {
                    "provider": provider.value,
                    "name": schema["name"],
                    "auth_scheme": schema.get("auth_scheme"),
                    "message_transport": schema.get("message_transport"),
                    "readiness": schema.get("readiness"),
                    "required_fields": schema["required_fields"],
                    "optional_fields": schema["optional_fields"],
                    "field_specs": schema.get("field_specs", []),
                    "capabilities": schema.get("capabilities", {}),
                    "notes": schema.get("notes", ""),
                }
            )
        return providers

    def validate_credentials(
        self,
        provider: IntegrationProvider,
        credentials: Dict[str, str],
    ) -> List[str]:
        schema = PROVIDER_SCHEMAS[provider]
        missing = [k for k in schema["required_fields"] if not credentials.get(k)]
        return missing

    def upsert_credentials(
        self,
        company_id: UUID,
        provider: IntegrationProvider,
        credentials: Dict[str, str],
        label: str | None = None,
    ) -> Dict[str, Any]:
        missing = self.validate_credentials(provider, credentials)
        if missing:
            raise ValueError(f"Missing required fields for {provider.value}: {missing}")

        data = self._load()
        company_key = str(company_id)
        company_data = data["companies"].setdefault(company_key, {})
        company_data[provider.value] = {
            "label": label or PROVIDER_SCHEMAS[provider]["name"],
            "credentials": credentials,
            "updated_at": _utcnow_iso(),
        }
        self._save(data)

        return {
            "company_id": company_key,
            "provider": provider.value,
            "label": company_data[provider.value]["label"],
            "updated_at": company_data[provider.value]["updated_at"],
            "credential_fields": sorted(list(credentials.keys())),
        }

    def list_configured(self, company_id: UUID) -> List[Dict[str, Any]]:
        data = self._load()
        company_data = data["companies"].get(str(company_id), {})
        configured: List[Dict[str, Any]] = []

        for provider_name, item in company_data.items():
            credential_keys = sorted(list(item.get("credentials", {}).keys()))
            sample_key = ""
            if credential_keys:
                sample_value = item["credentials"].get(credential_keys[0], "")
                sample_key = _mask_secret(str(sample_value))
            configured.append(
                {
                    "provider": provider_name,
                    "label": item.get("label") or provider_name,
                    "updated_at": item.get("updated_at"),
                    "credential_fields": credential_keys,
                    "masked_sample": sample_key,
                }
            )

        return configured

    def get_credentials(self, company_id: UUID, provider: IntegrationProvider) -> Dict[str, str]:
        data = self._load()
        company_data = data["companies"].get(str(company_id), {})
        provider_data = company_data.get(provider.value)
        if not provider_data:
            raise ValueError(f"No credentials stored for provider '{provider.value}'")
        return provider_data.get("credentials", {})

    def test_connection(
        self,
        provider: IntegrationProvider,
        credentials: Dict[str, str],
    ) -> Dict[str, Any]:
        missing = self.validate_credentials(provider, credentials)
        if missing:
            return {
                "ok": False,
                "message": f"Missing required fields: {missing}",
                "provider": provider.value,
            }

        # MVP: schema and credential shape checks only.
        provider_messages = {
            IntegrationProvider.BREEZEWAY: "Credential shape valid. Live Breezeway API ping can be enabled next.",
            IntegrationProvider.ESCAPIA: "Credential shape valid. Live Escapia PMS authentication can be enabled next.",
            IntegrationProvider.GUESTY: "Credential shape valid. Guesty property and booking sync can use the canonical PMS contract.",
            IntegrationProvider.HOSTAWAY: "Credential shape valid. Hostaway can plug into the canonical PMS contract once the dedicated adapter is completed.",
            IntegrationProvider.STREAMLINE: "Credential shape valid. Streamline is staged against the canonical PMS contract.",
            IntegrationProvider.LODGIFY: "Credential shape valid. Lodgify is staged against the canonical PMS contract.",
            IntegrationProvider.TRACK: "Credential shape valid. Track property and booking sync can use the canonical PMS contract.",
            IntegrationProvider.HOSTFULLY: "Credential shape valid. Hostfully is staged against the canonical PMS contract.",
            IntegrationProvider.OWNERREZ: "Credential shape valid. OwnerRez is staged against the canonical PMS contract.",
            IntegrationProvider.BEDS24: "Credential shape valid. Beds24 is staged against the canonical PMS contract.",
            IntegrationProvider.SMOOBU: "Credential shape valid. Smoobu is staged against the canonical PMS contract.",
            IntegrationProvider.WHEELHOUSE: "Credential shape valid. Live Wheelhouse API ping can be enabled next.",
        }
        return {
            "ok": True,
            "message": provider_messages[provider],
            "provider": provider.value,
        }


_store: IntegrationCredentialStore | None = None


def get_integration_credential_store() -> IntegrationCredentialStore:
    global _store
    if _store is None:
        _store = IntegrationCredentialStore()
    return _store
