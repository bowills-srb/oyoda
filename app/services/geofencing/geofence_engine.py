"""
Geofencing Engine - Geographic boundary management.

Enables property management companies to define geographic boundaries
for their market focus and automatically discover opportunities
within those boundaries.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import json
import logging
import math

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, TenantBaseModel

logger = logging.getLogger(__name__)


class GeofenceType(str, Enum):
    """Types of geofence definitions."""
    POLYGON = "polygon"  # Custom drawn polygon
    CIRCLE = "circle"    # Radius from center point
    ZIP_CODES = "zip_codes"  # Collection of ZIP codes
    COUNTY = "county"    # County boundary
    CITY = "city"        # City boundary
    MLS_AREA = "mls_area"  # MLS-defined area codes


class GeofencePurpose(str, Enum):
    """Purpose/use case for a geofence."""
    PRIMARY_MARKET = "primary_market"  # Main operating area
    EXPANSION_TARGET = "expansion_target"  # Target for growth
    MONITORING = "monitoring"  # Watch for competitive intelligence
    EXCLUSION = "exclusion"  # Area to exclude from results


class Geofence(TenantBaseModel, AuditMixin):
    """
    Geographic boundary definition.
    
    Companies can define multiple geofences to represent their
    market focus areas, expansion targets, and monitoring zones.
    """
    
    __tablename__ = "geofences"
    
    # Identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    # Type and purpose
    geofence_type: Mapped[GeofenceType] = mapped_column(
        String(50),
        default=GeofenceType.POLYGON
    )
    purpose: Mapped[GeofencePurpose] = mapped_column(
        String(50),
        default=GeofencePurpose.PRIMARY_MARKET
    )
    
    # Geometry - GeoJSON format
    # For POLYGON: {"type": "Polygon", "coordinates": [[[lng, lat], ...]]}
    # For CIRCLE: {"type": "Point", "coordinates": [lng, lat]}
    geometry: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    # For CIRCLE type - radius in miles
    radius_miles: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    
    # For ZIP_CODES type
    zip_codes: Mapped[list] = mapped_column(
        ARRAY(String(10)),
        default=list,
        server_default='{}'
    )
    
    # For COUNTY/CITY/MLS_AREA types
    area_codes: Mapped[list] = mapped_column(
        ARRAY(String(50)),
        default=list,
        server_default='{}'
    )
    
    # Bounding box (for quick filtering)
    bbox_min_lat: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    bbox_max_lat: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    bbox_min_lng: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    bbox_max_lng: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    
    # Buffer (expand boundary by this many miles)
    buffer_miles: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    
    # Status and monitoring
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Alert preferences
    alert_on_new_listing: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_on_price_change: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_on_status_change: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Statistics (updated periodically)
    property_count: Mapped[int] = mapped_column(Integer, default=0)
    active_listing_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_nightly_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    stats_updated_at: Mapped[Optional[datetime]] = mapped_column()
    
    # Metadata
    extra_data: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    
    def __repr__(self) -> str:
        return f"<Geofence(id={self.id}, name='{self.name}', type={self.geofence_type})>"


@dataclass
class Point:
    """A geographic point."""
    lat: float
    lng: float
    
    def to_tuple(self) -> Tuple[float, float]:
        return (self.lat, self.lng)
    
    @classmethod
    def from_geojson(cls, coords: List[float]) -> "Point":
        """Create from GeoJSON coordinates [lng, lat]."""
        return cls(lat=coords[1], lng=coords[0])


@dataclass 
class BoundingBox:
    """A geographic bounding box."""
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float
    
    def contains_point(self, point: Point) -> bool:
        """Check if a point is within this bounding box."""
        return (
            self.min_lat <= point.lat <= self.max_lat and
            self.min_lng <= point.lng <= self.max_lng
        )
    
    def expand(self, miles: float) -> "BoundingBox":
        """Expand the bounding box by a given number of miles."""
        # Approximate degrees per mile
        lat_per_mile = 1 / 69.0
        lng_per_mile = 1 / (69.0 * math.cos(math.radians((self.min_lat + self.max_lat) / 2)))
        
        return BoundingBox(
            min_lat=self.min_lat - (miles * lat_per_mile),
            max_lat=self.max_lat + (miles * lat_per_mile),
            min_lng=self.min_lng - (miles * lng_per_mile),
            max_lng=self.max_lng + (miles * lng_per_mile)
        )


class GeofenceEngine:
    """
    Engine for geofence operations.
    
    Provides methods for:
    - Creating and managing geofences
    - Point-in-polygon testing
    - Finding listings within geofences
    - Calculating geofence statistics
    """
    
    # Earth's radius in miles
    EARTH_RADIUS_MILES = 3959.0
    
    def __init__(self, db_session=None):
        self.db_session = db_session
    
    @staticmethod
    def haversine_distance(point1: Point, point2: Point) -> float:
        """
        Calculate the great-circle distance between two points in miles.
        
        Uses the Haversine formula.
        """
        lat1_rad = math.radians(point1.lat)
        lat2_rad = math.radians(point2.lat)
        delta_lat = math.radians(point2.lat - point1.lat)
        delta_lng = math.radians(point2.lng - point1.lng)
        
        a = (
            math.sin(delta_lat / 2) ** 2 +
            math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return GeofenceEngine.EARTH_RADIUS_MILES * c
    
    @staticmethod
    def point_in_polygon(point: Point, polygon_coords: List[List[float]]) -> bool:
        """
        Check if a point is inside a polygon using ray casting algorithm.
        
        Args:
            point: The point to test
            polygon_coords: List of [lng, lat] coordinates forming the polygon
        
        Returns:
            True if point is inside polygon
        """
        n = len(polygon_coords)
        inside = False
        
        p1_lng, p1_lat = polygon_coords[0]
        for i in range(1, n + 1):
            p2_lng, p2_lat = polygon_coords[i % n]
            
            if point.lat > min(p1_lat, p2_lat):
                if point.lat <= max(p1_lat, p2_lat):
                    if point.lng <= max(p1_lng, p2_lng):
                        if p1_lat != p2_lat:
                            lng_intersect = (
                                (point.lat - p1_lat) * (p2_lng - p1_lng) /
                                (p2_lat - p1_lat) + p1_lng
                            )
                        if p1_lng == p2_lng or point.lng <= lng_intersect:
                            inside = not inside
            
            p1_lng, p1_lat = p2_lng, p2_lat
        
        return inside
    
    @staticmethod
    def calculate_bounding_box(geometry: dict, geofence_type: GeofenceType, radius_miles: float = 0) -> BoundingBox:
        """Calculate the bounding box for a geofence geometry."""
        if geofence_type == GeofenceType.POLYGON:
            coords = geometry.get("coordinates", [[]])[0]  # Outer ring
            if not coords:
                raise ValueError("Polygon has no coordinates")
            
            lats = [c[1] for c in coords]
            lngs = [c[0] for c in coords]
            
            return BoundingBox(
                min_lat=min(lats),
                max_lat=max(lats),
                min_lng=min(lngs),
                max_lng=max(lngs)
            )
        
        elif geofence_type == GeofenceType.CIRCLE:
            center_coords = geometry.get("coordinates", [])
            if len(center_coords) != 2:
                raise ValueError("Circle must have center coordinates")
            
            center = Point.from_geojson(center_coords)
            
            # Calculate bounding box from center + radius
            lat_per_mile = 1 / 69.0
            lng_per_mile = 1 / (69.0 * math.cos(math.radians(center.lat)))
            
            return BoundingBox(
                min_lat=center.lat - (radius_miles * lat_per_mile),
                max_lat=center.lat + (radius_miles * lat_per_mile),
                min_lng=center.lng - (radius_miles * lng_per_mile),
                max_lng=center.lng + (radius_miles * lng_per_mile)
            )
        
        else:
            raise ValueError(f"Cannot calculate bounding box for type: {geofence_type}")
    
    def contains_point(
        self,
        geofence: Geofence,
        point: Point,
        include_buffer: bool = True
    ) -> bool:
        """
        Check if a point is contained within a geofence.
        
        Args:
            geofence: The geofence to test against
            point: The point to test
            include_buffer: Whether to include the buffer distance
        
        Returns:
            True if point is within the geofence
        """
        # Quick bounding box check first
        if all([geofence.bbox_min_lat, geofence.bbox_max_lat, 
                geofence.bbox_min_lng, geofence.bbox_max_lng]):
            bbox = BoundingBox(
                min_lat=float(geofence.bbox_min_lat),
                max_lat=float(geofence.bbox_max_lat),
                min_lng=float(geofence.bbox_min_lng),
                max_lng=float(geofence.bbox_max_lng)
            )
            
            if include_buffer and geofence.buffer_miles:
                bbox = bbox.expand(float(geofence.buffer_miles))
            
            if not bbox.contains_point(point):
                return False
        
        # Detailed check based on type
        if geofence.geofence_type == GeofenceType.POLYGON:
            return self._check_polygon(geofence, point, include_buffer)
        
        elif geofence.geofence_type == GeofenceType.CIRCLE:
            return self._check_circle(geofence, point, include_buffer)
        
        elif geofence.geofence_type == GeofenceType.ZIP_CODES:
            # Would need ZIP code lookup
            logger.warning("ZIP code geofence check not implemented - returning False")
            return False
        
        else:
            logger.warning(f"Geofence type {geofence.geofence_type} check not implemented")
            return False
    
    def _check_polygon(self, geofence: Geofence, point: Point, include_buffer: bool) -> bool:
        """Check if point is in polygon geofence."""
        coords = geofence.geometry.get("coordinates", [[]])[0]
        
        in_polygon = self.point_in_polygon(point, coords)
        
        if in_polygon:
            return True
        
        # If not in polygon but buffer is enabled, check distance to edge
        if include_buffer and geofence.buffer_miles and float(geofence.buffer_miles) > 0:
            min_distance = self._distance_to_polygon_edge(point, coords)
            return min_distance <= float(geofence.buffer_miles)
        
        return False
    
    def _check_circle(self, geofence: Geofence, point: Point, include_buffer: bool) -> bool:
        """Check if point is in circle geofence."""
        center_coords = geofence.geometry.get("coordinates", [])
        center = Point.from_geojson(center_coords)
        
        radius = float(geofence.radius_miles or 0)
        if include_buffer and geofence.buffer_miles:
            radius += float(geofence.buffer_miles)
        
        distance = self.haversine_distance(point, center)
        return distance <= radius
    
    def _distance_to_polygon_edge(self, point: Point, coords: List[List[float]]) -> float:
        """Calculate minimum distance from point to polygon edge."""
        min_distance = float('inf')
        
        for i in range(len(coords)):
            p1 = Point.from_geojson(coords[i])
            p2 = Point.from_geojson(coords[(i + 1) % len(coords)])
            
            # Distance to line segment
            dist = self._distance_to_segment(point, p1, p2)
            min_distance = min(min_distance, dist)
        
        return min_distance
    
    def _distance_to_segment(self, point: Point, seg_start: Point, seg_end: Point) -> float:
        """Calculate distance from point to line segment."""
        # Simplified - just use distance to closest endpoint
        # A proper implementation would project onto the segment
        d1 = self.haversine_distance(point, seg_start)
        d2 = self.haversine_distance(point, seg_end)
        return min(d1, d2)
    
    async def find_properties_in_geofence(
        self,
        geofence: Geofence,
        property_repository,
        filters: Dict[str, Any] = None
    ) -> List[Any]:
        """
        Find all properties within a geofence.
        
        Args:
            geofence: The geofence to search within
            property_repository: Repository for property queries
            filters: Additional filters to apply
        
        Returns:
            List of properties within the geofence
        """
        # Start with bounding box filter for efficiency
        bbox_filters = {
            "lat_gte": float(geofence.bbox_min_lat) if geofence.bbox_min_lat else None,
            "lat_lte": float(geofence.bbox_max_lat) if geofence.bbox_max_lat else None,
            "lng_gte": float(geofence.bbox_min_lng) if geofence.bbox_min_lng else None,
            "lng_lte": float(geofence.bbox_max_lng) if geofence.bbox_max_lng else None,
        }
        
        # Remove None values
        bbox_filters = {k: v for k, v in bbox_filters.items() if v is not None}
        
        # Merge with additional filters
        all_filters = {**bbox_filters, **(filters or {})}
        
        # Get candidate properties
        candidates = await property_repository.find_by_filters(all_filters)
        
        # Precise filtering
        results = []
        for prop in candidates:
            if prop.latitude and prop.longitude:
                point = Point(lat=float(prop.latitude), lng=float(prop.longitude))
                if self.contains_point(geofence, point):
                    results.append(prop)
        
        return results
    
    def create_circle_geofence(
        self,
        name: str,
        center_lat: float,
        center_lng: float,
        radius_miles: float,
        company_id: UUID,
        purpose: GeofencePurpose = GeofencePurpose.PRIMARY_MARKET,
        **kwargs
    ) -> Geofence:
        """
        Create a circular geofence.
        
        Args:
            name: Name of the geofence
            center_lat: Center latitude
            center_lng: Center longitude
            radius_miles: Radius in miles
            company_id: Company ID
            purpose: Purpose of the geofence
        
        Returns:
            New Geofence instance
        """
        geometry = {
            "type": "Point",
            "coordinates": [center_lng, center_lat]
        }
        
        bbox = self.calculate_bounding_box(
            geometry,
            GeofenceType.CIRCLE,
            radius_miles
        )
        
        return Geofence(
            company_id=company_id,
            name=name,
            geofence_type=GeofenceType.CIRCLE,
            purpose=purpose,
            geometry=geometry,
            radius_miles=radius_miles,
            bbox_min_lat=bbox.min_lat,
            bbox_max_lat=bbox.max_lat,
            bbox_min_lng=bbox.min_lng,
            bbox_max_lng=bbox.max_lng,
            **kwargs
        )
    
    def create_polygon_geofence(
        self,
        name: str,
        coordinates: List[List[float]],
        company_id: UUID,
        purpose: GeofencePurpose = GeofencePurpose.PRIMARY_MARKET,
        **kwargs
    ) -> Geofence:
        """
        Create a polygon geofence.
        
        Args:
            name: Name of the geofence
            coordinates: List of [lng, lat] coordinates forming the polygon
            company_id: Company ID
            purpose: Purpose of the geofence
        
        Returns:
            New Geofence instance
        """
        # Ensure polygon is closed
        if coordinates[0] != coordinates[-1]:
            coordinates = coordinates + [coordinates[0]]
        
        geometry = {
            "type": "Polygon",
            "coordinates": [coordinates]
        }
        
        bbox = self.calculate_bounding_box(geometry, GeofenceType.POLYGON)
        
        return Geofence(
            company_id=company_id,
            name=name,
            geofence_type=GeofenceType.POLYGON,
            purpose=purpose,
            geometry=geometry,
            bbox_min_lat=bbox.min_lat,
            bbox_max_lat=bbox.max_lat,
            bbox_min_lng=bbox.min_lng,
            bbox_max_lng=bbox.max_lng,
            **kwargs
        )


class GeofenceMonitor:
    """
    Monitors geofences for new listings and changes.
    
    Integrates with the Detector Engine to emit events when
    new properties appear within monitored geofences.
    """
    
    def __init__(
        self,
        geofence_engine: GeofenceEngine,
        detector_registry=None
    ):
        self.geofence_engine = geofence_engine
        self.detector_registry = detector_registry
    
    async def check_new_listing(
        self,
        property_data: Dict[str, Any],
        company_id: UUID
    ) -> List[Geofence]:
        """
        Check if a new listing falls within any monitored geofences.
        
        Args:
            property_data: Property data including lat/lng
            company_id: Company to check geofences for
        
        Returns:
            List of geofences the property falls within
        """
        lat = property_data.get("latitude")
        lng = property_data.get("longitude")
        
        if lat is None or lng is None:
            return []
        
        point = Point(lat=float(lat), lng=float(lng))
        
        # Get all active, monitored geofences for this company
        # In real implementation, this would query the database
        # geofences = await self.get_company_geofences(company_id, monitoring_enabled=True)
        
        matching_geofences = []
        
        # For now, return empty - in real implementation:
        # for geofence in geofences:
        #     if self.geofence_engine.contains_point(geofence, point):
        #         matching_geofences.append(geofence)
        #         
        #         # Emit detector event if enabled
        #         if geofence.alert_on_new_listing and self.detector_registry:
        #             property_data["within_geofence"] = True
        #             property_data["geofence_id"] = str(geofence.id)
        #             property_data["geofence_name"] = geofence.name
        
        return matching_geofences
