"""
Website Widget Integration

Instead of scraping an operator's website, we provide them with a
lightweight JavaScript widget they embed on their site.

Benefits over scraping:
1. Explicit operator authorization
2. Real-time data (not stale scrapes)
3. Access to booking widget data
4. No legal/ToS concerns
5. Works with any website builder

How it works:
1. Operator adds our <script> tag to their site
2. Widget detects their booking system (Lodgify, JERC, etc.)
3. Widget sends property data to our API
4. We also capture marketing content (descriptions, photos)

This is similar to how analytics tools (Google Analytics, Hotjar) work.
"""

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class BookingWidgetType(str, Enum):
    """Detected booking widget types."""
    LODGIFY = "lodgify"
    JERC = "jerc"           # JERC Rentals
    WEBREZ = "webrez"
    BOOKERVILLE = "bookerville"
    CIIRUS = "ciirus"
    DIRECT_BOOKING = "direct_booking"  # Custom forms
    AIRBNB_EMBED = "airbnb_embed"
    VRBO_EMBED = "vrbo_embed"
    UNKNOWN = "unknown"


@dataclass
class WidgetPropertyData:
    """Property data captured by the website widget."""
    # Identity
    page_url: str
    operator_id: str
    
    # Property info from page
    property_name: Optional[str] = None
    property_code: Optional[str] = None
    
    # Marketing content
    headline: Optional[str] = None
    description: Optional[str] = None
    photos: List[str] = field(default_factory=list)
    
    # Details extracted from page
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    
    # Amenities (extracted from page content)
    amenities: List[str] = field(default_factory=list)
    
    # Location
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    
    # Booking widget info
    widget_type: BookingWidgetType = BookingWidgetType.UNKNOWN
    widget_property_id: Optional[str] = None
    
    # Pricing (if visible on page)
    displayed_rate: Optional[str] = None  # e.g., "From $350/night"
    
    # Metadata
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    page_title: Optional[str] = None
    

@dataclass
class WidgetConfig:
    """Configuration for an operator's widget."""
    operator_id: str
    widget_id: str
    secret_key: str  # For HMAC validation
    
    # Allowed domains
    allowed_domains: List[str] = field(default_factory=list)
    
    # What to capture
    capture_photos: bool = True
    capture_descriptions: bool = True
    capture_pricing: bool = True
    
    # Settings
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class WebsiteWidget:
    """
    Manages the website widget integration.
    
    Usage:
        widget = WebsiteWidget()
        
        # Generate widget for operator
        config = widget.create_widget_config("op_beach_habitats", ["beachhabitats.com"])
        script_tag = widget.generate_script_tag(config)
        
        # Process incoming data from widget
        data = widget.process_widget_data(payload, headers)
    """
    
    def __init__(self, api_base_url: str = "https://api.concierge.ai"):
        self.api_base_url = api_base_url
    
    def create_widget_config(
        self,
        operator_id: str,
        allowed_domains: List[str],
    ) -> WidgetConfig:
        """Create a widget configuration for an operator."""
        import secrets
        
        widget_id = f"wgt_{secrets.token_hex(8)}"
        secret_key = secrets.token_hex(32)
        
        return WidgetConfig(
            operator_id=operator_id,
            widget_id=widget_id,
            secret_key=secret_key,
            allowed_domains=allowed_domains,
        )
    
    def generate_script_tag(self, config: WidgetConfig) -> str:
        """Generate the script tag for the operator to embed."""
        return f'''<!-- Concierge AI Property Sync -->
<script>
  (function() {{
    var s = document.createElement('script');
    s.src = '{self.api_base_url}/widget/v1/sync.js';
    s.async = true;
    s.dataset.widgetId = '{config.widget_id}';
    s.dataset.operatorId = '{config.operator_id}';
    document.head.appendChild(s);
  }})();
</script>'''
    
    def generate_widget_js(self, config: WidgetConfig) -> str:
        """Generate the widget JavaScript code with security."""
        template = '''
/**
 * Concierge AI Property Sync Widget
 * 
 * This script runs on the operator's website and:
 * 1. Detects property pages
 * 2. Extracts property information
 * 3. Identifies booking widget type
 * 4. Sends data to Concierge AI API
 */

(function() {
  'use strict';
  
  const CONFIG = {
    widgetId: document.currentScript.dataset.widgetId || '__WIDGET_ID__',
    operatorId: document.currentScript.dataset.operatorId || '__OPERATOR_ID__',
    apiEndpoint: '__API_ENDPOINT__',
  };
  
  // Detect if this is a property page
  function isPropertyPage() {
    // Look for common property page indicators
    const indicators = [
      // URL patterns
      /\\/property\\//i,
      /\\/listing\\//i,
      /\\/rental\\//i,
      /\\/vacation-rental\\//i,
      
      // Meta tags
      document.querySelector('meta[property="og:type"][content*="rental"]'),
      document.querySelector('meta[property="og:type"][content*="property"]'),
      
      // Schema.org
      document.querySelector('[itemtype*="Accommodation"]'),
      document.querySelector('[itemtype*="LodgingBusiness"]'),
      document.querySelector('[itemtype*="VacationRental"]'),
    ];
    
    return indicators.some(i => i);
  }
  
  // Extract property name
  function getPropertyName() {
    // Try common patterns
    const selectors = [
      'h1.property-name',
      'h1.listing-title',
      '[data-property-name]',
      '.property-header h1',
      'meta[property="og:title"]',
      'h1',
    ];
    
    for (const selector of selectors) {
      const el = document.querySelector(selector);
      if (el) {
        return el.content || el.textContent.trim();
      }
    }
    return document.title;
  }
  
  // Extract description
  function getDescription() {
    const selectors = [
      '.property-description',
      '.listing-description',
      '[data-description]',
      'meta[property="og:description"]',
      'meta[name="description"]',
    ];
    
    for (const selector of selectors) {
      const el = document.querySelector(selector);
      if (el) {
        return (el.content || el.textContent || '').trim().slice(0, 2000);
      }
    }
    return null;
  }
  
  // Extract photos
  function getPhotos() {
    const photos = [];
    
    // Gallery images
    document.querySelectorAll('.property-gallery img, .listing-photos img, [data-gallery] img').forEach(img => {
      if (img.src && !img.src.includes('placeholder')) {
        photos.push(img.src);
      }
    });
    
    // OG image
    const ogImage = document.querySelector('meta[property="og:image"]');
    if (ogImage && ogImage.content) {
      photos.unshift(ogImage.content);
    }
    
    return [...new Set(photos)].slice(0, 20);
  }
  
  // Extract bedroom/bathroom counts
  function getPropertyDetails() {
    const details = {};
    
    // Look for structured data
    const text = document.body.innerText;
    
    const bedroomMatch = text.match(/(\\d+)\\s*(?:bed(?:room)?s?|BR)/i);
    if (bedroomMatch) details.bedrooms = parseInt(bedroomMatch[1]);
    
    const bathroomMatch = text.match(/(\\d+(?:\\.\\d)?)\\s*(?:bath(?:room)?s?|BA)/i);
    if (bathroomMatch) details.bathrooms = parseFloat(bathroomMatch[1]);
    
    const sleepsMatch = text.match(/(?:sleeps?|accommodates?)\\s*(\\d+)/i);
    if (sleepsMatch) details.sleeps = parseInt(sleepsMatch[1]);
    
    return details;
  }
  
  // Detect booking widget type
  function detectWidgetType() {
    // Lodgify
    if (document.querySelector('[class*="lodgify"], script[src*="lodgify"]')) {
      return 'lodgify';
    }
    
    // JERC
    if (document.querySelector('[class*="jerc"], script[src*="jerc"]')) {
      return 'jerc';
    }
    
    // Bookerville
    if (document.querySelector('script[src*="bookerville"]')) {
      return 'bookerville';
    }
    
    // Airbnb embed
    if (document.querySelector('[class*="airbnb"], iframe[src*="airbnb"]')) {
      return 'airbnb_embed';
    }
    
    // VRBO embed
    if (document.querySelector('iframe[src*="vrbo"], iframe[src*="homeaway"]')) {
      return 'vrbo_embed';
    }
    
    return 'unknown';
  }
  
  // Extract amenities
  function getAmenities() {
    const amenities = [];
    
    document.querySelectorAll('.amenity, .amenities li, [data-amenity]').forEach(el => {
      const text = el.textContent.trim();
      if (text && text.length < 50) {
        amenities.push(text);
      }
    });
    
    return amenities.slice(0, 50);
  }
  
  // Collect and send data
  function syncPropertyData() {
    if (!isPropertyPage()) {
      return;
    }
    
    const details = getPropertyDetails();
    
    const data = {
      widget_id: CONFIG.widgetId,
      operator_id: CONFIG.operatorId,
      page_url: window.location.href,
      page_title: document.title,
      
      property_name: getPropertyName(),
      description: getDescription(),
      photos: getPhotos(),
      
      bedrooms: details.bedrooms,
      bathrooms: details.bathrooms,
      sleeps: details.sleeps,
      
      amenities: getAmenities(),
      widget_type: detectWidgetType(),
      
      captured_at: new Date().toISOString(),
    };
    
    // Send to API
    fetch(CONFIG.apiEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    }).catch(err => console.error('Concierge sync error:', err));
  }
  
  // Run on page load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncPropertyData);
  } else {
    syncPropertyData();
  }
  
})();
'''
        return (
            template
            .replace("__WIDGET_ID__", config.widget_id)
            .replace("__OPERATOR_ID__", config.operator_id)
            .replace("__API_ENDPOINT__", f"{self.api_base_url}/widget/v1/sync")
        )
    
    def validate_payload(
        self,
        payload: Dict[str, Any],
        signature: str,
        config: WidgetConfig,
    ) -> bool:
        """Validate incoming webhook payload."""
        # Compute expected signature
        payload_str = json.dumps(payload, sort_keys=True)
        expected = hmac.new(
            config.secret_key.encode(),
            payload_str.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected)
    
    def process_widget_data(
        self,
        payload: Dict[str, Any],
        config: WidgetConfig,
    ) -> WidgetPropertyData:
        """Process incoming data from the widget."""
        # Validate domain
        page_url = payload.get('page_url', '')
        domain = page_url.split('/')[2] if '//' in page_url else ''
        
        if config.allowed_domains:
            if not any(d in domain for d in config.allowed_domains):
                raise ValueError(f"Domain not allowed: {domain}")
        
        return WidgetPropertyData(
            page_url=page_url,
            operator_id=config.operator_id,
            property_name=payload.get('property_name'),
            description=payload.get('description'),
            photos=payload.get('photos', []),
            bedrooms=payload.get('bedrooms'),
            bathrooms=payload.get('bathrooms'),
            sleeps=payload.get('sleeps'),
            amenities=payload.get('amenities', []),
            widget_type=BookingWidgetType(payload.get('widget_type', 'unknown')),
            page_title=payload.get('page_title'),
        )


class OAuthIntegration:
    """
    OAuth-based integrations with OTAs.
    
    Instead of scraping, we can have operators authorize us
    to access their Airbnb/VRBO accounts directly.
    
    This gives us:
    - Accurate listing data
    - Reviews
    - Booking history
    - Real-time availability
    """
    
    # OAuth configs for major platforms
    OAUTH_CONFIGS = {
        'airbnb': {
            'name': 'Airbnb',
            'auth_url': 'https://www.airbnb.com/oauth2/auth',
            'token_url': 'https://api.airbnb.com/v2/oauth2/token',
            'scopes': ['listings:read', 'reservations:read'],
            'requires_partnership': True,  # Need Airbnb API partnership
        },
        'vrbo': {
            'name': 'VRBO/Expedia',
            'auth_url': 'https://www.expediapartnersolutions.com/oauth/authorize',
            'token_url': 'https://www.expediapartnersolutions.com/oauth/token',
            'scopes': ['property.read', 'booking.read'],
            'requires_partnership': True,
        },
        'booking_com': {
            'name': 'Booking.com',
            'auth_url': 'https://account.booking.com/oauth2/authorize',
            'token_url': 'https://account.booking.com/oauth2/token',
            'scopes': ['property_api', 'reservations_api'],
            'requires_partnership': True,
        },
        'google_business': {
            'name': 'Google Business Profile',
            'auth_url': 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url': 'https://oauth2.googleapis.com/token',
            'scopes': [
                'https://www.googleapis.com/auth/business.manage',
            ],
            'requires_partnership': False,  # Public API
        },
    }
    
    def generate_oauth_url(
        self,
        platform: str,
        operator_id: str,
        redirect_uri: str,
        client_id: str,
    ) -> str:
        """Generate OAuth authorization URL for a platform."""
        config = self.OAUTH_CONFIGS.get(platform)
        if not config:
            raise ValueError(f"Unknown platform: {platform}")
        
        import urllib.parse
        
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(config['scopes']),
            'state': f"{operator_id}:{platform}",
        }
        
        return f"{config['auth_url']}?{urllib.parse.urlencode(params)}"
    
    def get_available_integrations(self) -> List[Dict[str, Any]]:
        """Get list of available OAuth integrations."""
        return [
            {
                'platform': key,
                'name': config['name'],
                'requires_partnership': config['requires_partnership'],
                'scopes': config['scopes'],
            }
            for key, config in self.OAUTH_CONFIGS.items()
        ]
