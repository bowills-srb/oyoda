from app.services.connectors.pms_connectors import PMSProvider
from app.services.orchestration import (
    MessagingBrainDomain,
    MessagingLifecycle,
    MessagingBrainStage,
    MessagingBrainRegistry,
    build_pms_connection_contract,
    get_default_messaging_brain_registry,
)


def test_build_pms_connection_contract_maps_provider_contract():
    contract = build_pms_connection_contract(PMSProvider.ESCAPIA)

    assert contract.connector_key == "escapia"
    assert contract.domain == MessagingBrainDomain.PMS
    assert contract.auth_scheme == "api_key"
    assert contract.message_transport == "email_bridge"
    assert contract.capabilities["listings"] is True
    assert "provider_property_id" in contract.produces


def test_default_messaging_brain_registry_exposes_core_module_and_pms_contracts():
    registry = get_default_messaging_brain_registry()

    messaging_core = registry.get_module_contract("messaging_core")
    escapia = registry.get_connection_contract("escapia")

    assert messaging_core.domain == MessagingBrainDomain.MESSAGING
    assert MessagingBrainStage.DRAFT in messaging_core.consumes_stages
    assert MessagingLifecycle.PRE_BOOKING in messaging_core.supports_lifecycles
    assert escapia.domain == MessagingBrainDomain.PMS
    assert escapia.connector_key == "escapia"


def test_registry_filters_module_contracts_by_domain_and_lifecycle():
    registry = MessagingBrainRegistry.with_defaults()

    maintenance_contracts = registry.list_module_contracts(
        domain=MessagingBrainDomain.MAINTENANCE,
        lifecycle=MessagingLifecycle.IN_STAY,
    )
    prebooking_maintenance = registry.list_module_contracts(
        domain=MessagingBrainDomain.MAINTENANCE,
        lifecycle=MessagingLifecycle.PRE_BOOKING,
    )

    assert len(maintenance_contracts) == 1
    assert maintenance_contracts[0].module_key == "maintenance"
    assert prebooking_maintenance == []


def test_registry_lists_planned_and_implemented_pms_connection_contracts():
    registry = MessagingBrainRegistry.with_defaults()

    pms_contracts = registry.list_connection_contracts(domain=MessagingBrainDomain.PMS)
    implemented = registry.list_connection_contracts(
        domain=MessagingBrainDomain.PMS,
        readiness="implemented",
    )

    connector_keys = {contract.connector_key for contract in pms_contracts}
    implemented_keys = {contract.connector_key for contract in implemented}

    assert "escapia" in connector_keys
    assert "guesty" in connector_keys
    assert "ownerrez" in connector_keys
    assert "escapia" in implemented_keys
