"""
Unified Property Sync Service

Orchestrates data collection from all sources and handles deduplication.

Flow:
1. PMS sync (primary source)
2. Supplement with other sources (widget, OAuth, files)
3. Deduplicate and merge
4. Index into knowledge base

Key principle: PMS is authoritative, other sources supplement.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.integrations.deduplication import (
    DataSource,
    PropertyDeduplicator,
    DataMerger,
    SourcedField,
    PropertyMatch,
)
from app.services.connectors.pms_connectors import (
    PMSConnector,
    CanonicalListing as PMSProperty,
    CanonicalBooking as PMSBooking,
)

logger = logging.getLogger(__name__)


@dataclass
class UnifiedProperty:
    """
    Property with data merged from multiple sources.
    Tracks which source each field came from.
    """
    id: str  # Our internal ID
    operator_id: str
    
    # Source tracking
    primary_source: DataSource
    sources: Set[DataSource] = field(default_factory=set)
    
    # External IDs
    pms_external_id: Optional[str] = None
    pms_provider: Optional[str] = None
    airbnb_id: Optional[str] = None
    vrbo_id: Optional[str] = None
    
    # Merged data (with source tracking)
    data: Dict[str, SourcedField] = field(default_factory=dict)
    
    # Sync metadata
    last_synced_at: datetime = field(default_factory=datetime.utcnow)
    sync_errors: List[str] = field(default_factory=list)
    
    def get(self, field_name: str, default: Any = None) -> Any:
        """Get a field value."""
        if field_name in self.data:
            return self.data[field_name].value
        return default
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to flat dictionary."""
        result = {
            'id': self.id,
            'operator_id': self.operator_id,
            'primary_source': self.primary_source.value,
            'sources': [s.value for s in self.sources],
            'pms_external_id': self.pms_external_id,
            'pms_provider': self.pms_provider,
        }
        
        for field_name, sourced in self.data.items():
            result[field_name] = sourced.value
        
        return result


@dataclass
class SyncStats:
    """Statistics from a sync operation."""
    operator_id: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Source stats
    pms_properties: int = 0
    widget_properties: int = 0
    file_properties: int = 0
    
    # Deduplication
    total_raw: int = 0
    duplicates_found: int = 0
    properties_created: int = 0
    properties_updated: int = 0
    
    # Field coverage
    fields_filled: Dict[str, int] = field(default_factory=dict)
    fields_missing: Dict[str, int] = field(default_factory=dict)
    
    # Errors
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class PropertySyncService:
    """
    Unified service for syncing property data from all sources.
    
    Usage:
        sync_service = PropertySyncService(db_session)
        
        # Full sync from all available sources
        stats = await sync_service.sync_operator(
            operator_id="op_beach_habitats",
            pms_connector=escapia_connector,
            include_widget=True,
            include_files=True,
        )
        
        # Get merged property data
        properties = await sync_service.get_operator_properties("op_beach_habitats")
    """
    
    # Required fields for a complete property
    REQUIRED_FIELDS = {
        'name', 'address', 'bedrooms', 'bathrooms',
    }
    
    # Important fields for concierge
    CONCIERGE_FIELDS = {
        'wifi_network', 'wifi_password',
        'door_code', 'check_in_time', 'check_out_time',
    }
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.deduplicator = PropertyDeduplicator()
        self.merger = DataMerger()
        
        # In-memory cache (replace with Redis in production)
        self._properties: Dict[str, UnifiedProperty] = {}
    
    async def sync_operator(
        self,
        operator_id: str,
        pms_connector: Optional[PMSConnector] = None,
        widget_data: Optional[List[Dict]] = None,
        file_data: Optional[List[Dict]] = None,
    ) -> SyncStats:
        """
        Sync all property data for an operator.
        
        Priority order:
        1. PMS (authoritative)
        2. Widget data
        3. File data
        
        Later sources only fill in missing fields.
        """
        stats = SyncStats(operator_id=operator_id)
        
        try:
            # Phase 1: PMS Sync (primary source)
            if pms_connector:
                await self._sync_from_pms(operator_id, pms_connector, stats)
            
            # Phase 2: Widget data (supplementary)
            if widget_data:
                await self._sync_from_widget(operator_id, widget_data, stats)
            
            # Phase 3: File data (supplementary)
            if file_data:
                await self._sync_from_files(operator_id, file_data, stats)
            
            # Phase 4: Analyze coverage
            self._analyze_coverage(operator_id, stats)
            
            stats.completed_at = datetime.utcnow()
            
        except Exception as e:
            stats.errors.append(str(e))
            logger.error(f"Sync error for {operator_id}: {e}")
        
        return stats
    
    async def _sync_from_pms(
        self,
        operator_id: str,
        connector: PMSConnector,
        stats: SyncStats,
    ):
        """Sync properties from PMS."""
        logger.info(f"Syncing PMS data for {operator_id}")
        
        try:
            pms_properties = await connector.get_properties()
            stats.pms_properties = len(pms_properties)
            stats.total_raw += len(pms_properties)
            
            for pms_prop in pms_properties:
                # Check for existing property
                match = self.deduplicator.find_match(
                    address=pms_prop.address,
                    name=pms_prop.name,
                    bedrooms=pms_prop.bedrooms,
                    pms_provider=connector.provider.value,
                    pms_external_id=pms_prop.external_id,
                )
                
                if match.is_duplicate and match.matched_property_id:
                    # Update existing property
                    existing = self._properties.get(match.matched_property_id)
                    if existing:
                        self._merge_pms_property(existing, pms_prop)
                        stats.properties_updated += 1
                    stats.duplicates_found += 1
                else:
                    # Create new property
                    unified = self._create_from_pms(operator_id, pms_prop, connector.provider.value)
                    self._properties[unified.id] = unified
                    
                    # Register for deduplication
                    self.deduplicator.register_property(
                        property_id=unified.id,
                        address=pms_prop.address,
                        name=pms_prop.name,
                        pms_provider=connector.provider.value,
                        pms_external_id=pms_prop.external_id,
                    )
                    
                    stats.properties_created += 1
                    
        except Exception as e:
            stats.errors.append(f"PMS sync error: {e}")
            logger.error(f"PMS sync error: {e}")
    
    async def _sync_from_widget(
        self,
        operator_id: str,
        widget_data: List[Dict],
        stats: SyncStats,
    ):
        """Sync properties from website widget data."""
        logger.info(f"Processing {len(widget_data)} widget records for {operator_id}")
        
        stats.widget_properties = len(widget_data)
        stats.total_raw += len(widget_data)
        
        for data in widget_data:
            # Try to match to existing property
            match = self.deduplicator.find_match(
                address=data.get('address'),
                name=data.get('property_name'),
                bedrooms=data.get('bedrooms'),
            )
            
            if match.is_duplicate and match.matched_property_id:
                # Supplement existing property
                existing = self._properties.get(match.matched_property_id)
                if existing:
                    self._merge_widget_data(existing, data)
                stats.duplicates_found += 1
            else:
                # Create new property from widget data
                unified = self._create_from_widget(operator_id, data)
                self._properties[unified.id] = unified
                
                self.deduplicator.register_property(
                    property_id=unified.id,
                    address=data.get('address'),
                    name=data.get('property_name'),
                )
                
                stats.properties_created += 1
                stats.warnings.append(
                    f"Property '{data.get('property_name')}' only found in widget, not PMS"
                )
    
    async def _sync_from_files(
        self,
        operator_id: str,
        file_data: List[Dict],
        stats: SyncStats,
    ):
        """Sync properties from local file data."""
        logger.info(f"Processing {len(file_data)} file records for {operator_id}")
        
        stats.file_properties = len(file_data)
        stats.total_raw += len(file_data)
        
        for data in file_data:
            # File data typically has property codes
            property_code = data.get('code') or data.get('property_code')
            
            # Try to match by code first
            matched_id = None
            for prop_id, prop in self._properties.items():
                if prop.get('code') == property_code:
                    matched_id = prop_id
                    break
            
            if not matched_id:
                # Try address/name match
                match = self.deduplicator.find_match(
                    address=data.get('address'),
                    name=data.get('name'),
                    bedrooms=data.get('bedrooms'),
                )
                if match.is_duplicate:
                    matched_id = match.matched_property_id
            
            if matched_id:
                existing = self._properties.get(matched_id)
                if existing:
                    self._merge_file_data(existing, data)
                stats.duplicates_found += 1
            else:
                # Warn about unmatched file data
                stats.warnings.append(
                    f"File data for '{property_code or data.get('name')}' "
                    f"could not be matched to any property"
                )
    
    def _create_from_pms(
        self,
        operator_id: str,
        pms_prop: PMSProperty,
        pms_provider: str,
    ) -> UnifiedProperty:
        """Create unified property from PMS data."""
        unified = UnifiedProperty(
            id=f"prop_{uuid4().hex[:12]}",
            operator_id=operator_id,
            primary_source=DataSource.PMS,
            sources={DataSource.PMS},
            pms_external_id=pms_prop.external_id,
            pms_provider=pms_provider,
        )
        
        # Map PMS fields to unified format
        field_mapping = {
            'name': pms_prop.name,
            'code': pms_prop.code,
            'address': pms_prop.address,
            'city': pms_prop.city,
            'state': pms_prop.state,
            'postal_code': pms_prop.postal_code,
            'bedrooms': pms_prop.bedrooms,
            'bathrooms': pms_prop.bathrooms,
            'sleeps': pms_prop.sleeps,
            'wifi_network': pms_prop.wifi_network,
            'wifi_password': pms_prop.wifi_password,
            'door_code': pms_prop.door_code,
            'gate_code': pms_prop.gate_code,
            'check_in_time': pms_prop.check_in_time,
            'check_out_time': pms_prop.check_out_time,
            'description': pms_prop.description,
            'amenities': pms_prop.amenities,
            'photos': pms_prop.photos,
            'house_rules': pms_prop.house_rules,
            'base_rate': pms_prop.base_rate,
            'cleaning_fee': pms_prop.cleaning_fee,
        }
        
        for field_name, value in field_mapping.items():
            if value is not None:
                unified.data[field_name] = SourcedField(
                    value=value,
                    source=DataSource.PMS,
                )
        
        return unified
    
    def _create_from_widget(
        self,
        operator_id: str,
        data: Dict,
    ) -> UnifiedProperty:
        """Create unified property from widget data."""
        unified = UnifiedProperty(
            id=f"prop_{uuid4().hex[:12]}",
            operator_id=operator_id,
            primary_source=DataSource.WEBSITE_WIDGET,
            sources={DataSource.WEBSITE_WIDGET},
        )
        
        field_mapping = {
            'name': data.get('property_name'),
            'description': data.get('description'),
            'bedrooms': data.get('bedrooms'),
            'bathrooms': data.get('bathrooms'),
            'sleeps': data.get('sleeps'),
            'amenities': data.get('amenities'),
            'photos': data.get('photos'),
        }
        
        for field_name, value in field_mapping.items():
            if value is not None:
                unified.data[field_name] = SourcedField(
                    value=value,
                    source=DataSource.WEBSITE_WIDGET,
                )
        
        return unified
    
    def _merge_pms_property(
        self,
        existing: UnifiedProperty,
        pms_prop: PMSProperty,
    ):
        """Merge PMS data into existing property (PMS is authoritative)."""
        existing.sources.add(DataSource.PMS)
        existing.pms_external_id = pms_prop.external_id
        
        # PMS always wins for these fields
        pms_data = {
            'name': pms_prop.name,
            'address': pms_prop.address,
            'bedrooms': pms_prop.bedrooms,
            'bathrooms': pms_prop.bathrooms,
            'check_in_time': pms_prop.check_in_time,
            'check_out_time': pms_prop.check_out_time,
        }
        
        existing.data = self.merger.merge_property(
            existing.data,
            pms_data,
            DataSource.PMS,
        )
    
    def _merge_widget_data(
        self,
        existing: UnifiedProperty,
        data: Dict,
    ):
        """Merge widget data into existing property (supplements only)."""
        existing.sources.add(DataSource.WEBSITE_WIDGET)
        
        widget_data = {
            'description': data.get('description'),
            'photos': data.get('photos'),
            'amenities': data.get('amenities'),
        }
        
        existing.data = self.merger.merge_property(
            existing.data,
            widget_data,
            DataSource.WEBSITE_WIDGET,
        )
    
    def _merge_file_data(
        self,
        existing: UnifiedProperty,
        data: Dict,
    ):
        """Merge file data into existing property (supplements only)."""
        existing.sources.add(DataSource.LOCAL_FILES)
        
        # Files often have operational data PMS doesn't
        file_data = {
            'wifi_network': data.get('wifi_network') or data.get('wifi'),
            'wifi_password': data.get('wifi_password') or data.get('password'),
            'door_code': data.get('door_code'),
            'gate_code': data.get('gate_code'),
            'parking_instructions': data.get('parking_instructions'),
        }
        
        existing.data = self.merger.merge_property(
            existing.data,
            file_data,
            DataSource.LOCAL_FILES,
        )
    
    def _analyze_coverage(self, operator_id: str, stats: SyncStats):
        """Analyze field coverage across properties."""
        operator_properties = [
            p for p in self._properties.values()
            if p.operator_id == operator_id
        ]
        
        all_fields = self.REQUIRED_FIELDS | self.CONCIERGE_FIELDS
        
        for field_name in all_fields:
            filled = sum(1 for p in operator_properties if p.get(field_name))
            missing = len(operator_properties) - filled
            
            stats.fields_filled[field_name] = filled
            stats.fields_missing[field_name] = missing
            
            if missing > 0 and field_name in self.REQUIRED_FIELDS:
                stats.warnings.append(
                    f"{missing} properties missing required field: {field_name}"
                )
    
    async def get_operator_properties(
        self,
        operator_id: str,
    ) -> List[UnifiedProperty]:
        """Get all properties for an operator."""
        return [
            p for p in self._properties.values()
            if p.operator_id == operator_id
        ]
    
    async def get_property(self, property_id: str) -> Optional[UnifiedProperty]:
        """Get a single property by ID."""
        return self._properties.get(property_id)
    
    def get_missing_fields_summary(
        self,
        operator_id: str,
    ) -> Dict[str, List[str]]:
        """
        Get summary of which properties are missing which fields.
        
        Returns: {field_name: [list of property names missing it]}
        """
        operator_properties = [
            p for p in self._properties.values()
            if p.operator_id == operator_id
        ]
        
        missing = {}
        important_fields = self.REQUIRED_FIELDS | self.CONCIERGE_FIELDS
        
        for field_name in important_fields:
            missing_props = [
                p.get('name', p.id)
                for p in operator_properties
                if not p.get(field_name)
            ]
            if missing_props:
                missing[field_name] = missing_props
        
        return missing
