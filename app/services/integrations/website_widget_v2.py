"""
Website Widget Integration - Production Ready

SIMPLIFIED APPROACH:
Instead of trying to scrape arbitrary websites, we:
1. Provide a simple JavaScript snippet
2. Operator manually maps their property IDs to ours
3. Widget just pings us when a property page is viewed

This is MORE reliable than auto-detection.
"""

import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


@dataclass
class WidgetConfig:
    """Configuration for an operator's widget."""
    operator_id: str
    widget_id: str
    secret_key: str
    allowed_domains: List[str] = field(default_factory=list)
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PropertyMapping:
    """Maps operator's website property ID to our system."""
    operator_id: str
    website_property_id: str  # Their ID on their site
    our_property_id: str      # Our internal ID
    page_url_pattern: str     # e.g., "/property/{id}" or "/rentals/sea-la-vie"


class WebsiteWidgetV2:
    """
    Simplified widget integration.
    
    Approach:
    1. Operator embeds our script
    2. Script detects which property page they're on
    3. Script shows a chat button for that property
    4. We know the context without scraping
    
    This is similar to Intercom/Drift - simple and reliable.
    """
    
    def __init__(self, api_base_url: str = "https://api.beachhabitats.ai"):
        self.api_base_url = api_base_url
    
    def create_widget_config(
        self,
        operator_id: str,
        allowed_domains: List[str],
    ) -> WidgetConfig:
        """Create widget configuration."""
        return WidgetConfig(
            operator_id=operator_id,
            widget_id=f"wgt_{secrets.token_hex(8)}",
            secret_key=secrets.token_hex(32),
            allowed_domains=allowed_domains,
        )
    
    def generate_embed_code(self, config: WidgetConfig) -> str:
        """
        Generate the embed code for the operator.
        
        This is what they paste into their website.
        """
        return f'''<!-- Beach Habitats Concierge Widget -->
<script>
  window.bhConcierge = {{
    widgetId: '{config.widget_id}',
    operatorId: '{config.operator_id}'
  }};
</script>
<script async src="{self.api_base_url}/widget/v2/concierge.js"></script>
'''
    
    def generate_widget_script(self) -> str:
        """
        Generate the actual widget JavaScript.
        
        This is served from /widget/v2/concierge.js
        """
        return '''
(function() {
  'use strict';
  
  // Get config
  var config = window.bhConcierge || {};
  if (!config.widgetId || !config.operatorId) {
    console.warn('Beach Habitats: Missing widget configuration');
    return;
  }
  
  // API endpoint
  var API_BASE = 'https://api.beachhabitats.ai';
  
  // Create chat button
  function createButton() {
    var btn = document.createElement('div');
    btn.id = 'bh-chat-btn';
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="28" height="28" fill="white"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>';
    btn.style.cssText = 'position:fixed;bottom:20px;right:20px;width:60px;height:60px;' +
      'background:#0066cc;border-radius:50%;cursor:pointer;display:flex;' +
      'align-items:center;justify-content:center;box-shadow:0 4px 12px rgba(0,0,0,0.15);' +
      'z-index:9999;transition:transform 0.2s;';
    btn.onmouseenter = function() { btn.style.transform = 'scale(1.1)'; };
    btn.onmouseleave = function() { btn.style.transform = 'scale(1)'; };
    btn.onclick = openChat;
    document.body.appendChild(btn);
  }
  
  // Create chat modal
  function createModal() {
    var modal = document.createElement('div');
    modal.id = 'bh-chat-modal';
    modal.style.cssText = 'position:fixed;bottom:90px;right:20px;width:380px;height:520px;' +
      'background:white;border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,0.2);' +
      'z-index:9998;display:none;flex-direction:column;overflow:hidden;';
    
    modal.innerHTML = '' +
      '<div style="background:#0066cc;color:white;padding:16px;display:flex;align-items:center;justify-content:space-between;">' +
        '<span style="font-weight:600;font-size:16px;">🏖️ Beach Concierge</span>' +
        '<span id="bh-close" style="cursor:pointer;font-size:24px;">&times;</span>' +
      '</div>' +
      '<div id="bh-messages" style="flex:1;overflow-y:auto;padding:16px;"></div>' +
      '<div style="padding:12px;border-top:1px solid #eee;display:flex;gap:8px;">' +
        '<input id="bh-input" type="text" placeholder="Ask me anything..." ' +
          'style="flex:1;padding:10px 14px;border:1px solid #ddd;border-radius:20px;outline:none;">' +
        '<button id="bh-send" style="background:#0066cc;color:white;border:none;' +
          'border-radius:20px;padding:10px 16px;cursor:pointer;">Send</button>' +
      '</div>';
    
    document.body.appendChild(modal);
    
    // Event listeners
    document.getElementById('bh-close').onclick = closeChat;
    document.getElementById('bh-send').onclick = sendMessage;
    document.getElementById('bh-input').onkeypress = function(e) {
      if (e.key === 'Enter') sendMessage();
    };
  }
  
  // Get property context from URL
  function getPropertyContext() {
    var path = window.location.pathname;
    var search = window.location.search;
    
    // Common patterns
    var patterns = [
      /\\/property\\/([\\w-]+)/i,
      /\\/listing\\/([\\w-]+)/i,
      /\\/rentals?\\/([\\w-]+)/i,
      /[?&]property[_-]?id=([\\w-]+)/i,
      /[?&]listing[_-]?id=([\\w-]+)/i
    ];
    
    for (var i = 0; i < patterns.length; i++) {
      var match = (path + search).match(patterns[i]);
      if (match) return match[1];
    }
    
    return null;
  }
  
  // Open chat
  function openChat() {
    var modal = document.getElementById('bh-chat-modal');
    modal.style.display = 'flex';
    
    // Add welcome message if empty
    var messages = document.getElementById('bh-messages');
    if (!messages.innerHTML) {
      addMessage('assistant', "Hi! 👋 I'm your beach concierge. How can I help you today?");
    }
  }
  
  // Close chat
  function closeChat() {
    document.getElementById('bh-chat-modal').style.display = 'none';
  }
  
  // Add message to chat
  function addMessage(role, text) {
    var messages = document.getElementById('bh-messages');
    var isUser = role === 'user';
    
    var msg = document.createElement('div');
    msg.style.cssText = 'margin-bottom:12px;display:flex;' + 
      (isUser ? 'justify-content:flex-end;' : '');
    
    var bubble = document.createElement('div');
    bubble.style.cssText = 'max-width:80%;padding:10px 14px;border-radius:16px;' +
      (isUser ? 'background:#0066cc;color:white;' : 'background:#f0f0f0;color:#333;');
    bubble.textContent = text;
    
    msg.appendChild(bubble);
    messages.appendChild(msg);
    messages.scrollTop = messages.scrollHeight;
  }
  
  // Send message
  function sendMessage() {
    var input = document.getElementById('bh-input');
    var text = input.value.trim();
    if (!text) return;
    
    input.value = '';
    addMessage('user', text);
    
    // Show typing indicator
    var typing = document.createElement('div');
    typing.id = 'bh-typing';
    typing.style.cssText = 'margin-bottom:12px;';
    typing.innerHTML = '<div style="background:#f0f0f0;padding:10px 14px;border-radius:16px;display:inline-block;">...</div>';
    document.getElementById('bh-messages').appendChild(typing);
    
    // Send to API
    fetch(API_BASE + '/widget/v2/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        widget_id: config.widgetId,
        operator_id: config.operatorId,
        property_context: getPropertyContext(),
        page_url: window.location.href,
        message: text
      })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var t = document.getElementById('bh-typing');
      if (t) t.remove();
      addMessage('assistant', data.response || data.message || 'Sorry, I had trouble with that.');
    })
    .catch(function(err) {
      var t = document.getElementById('bh-typing');
      if (t) t.remove();
      addMessage('assistant', 'Sorry, I\\'m having connection issues. Please try again.');
    });
  }
  
  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  
  function init() {
    createButton();
    createModal();
  }
  
})();
'''
    
    def generate_api_endpoint_code(self) -> str:
        """
        Generate the FastAPI endpoint for widget chat.
        
        This goes in app/api/v1/endpoints/widget.py
        """
        return '''
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.knowledge import get_librarian_agent, create_voice_pod

router = APIRouter(prefix="/widget/v2", tags=["widget"])


class WidgetChatRequest(BaseModel):
    widget_id: str
    operator_id: str
    property_context: Optional[str] = None
    page_url: Optional[str] = None
    message: str


class WidgetChatResponse(BaseModel):
    response: str
    property_id: Optional[str] = None


@router.post("/chat", response_model=WidgetChatResponse)
async def widget_chat(request: WidgetChatRequest):
    """Handle chat from website widget."""
    
    # TODO: Validate widget_id belongs to operator_id
    
    # Create voice pod for this operator
    voice_pod = create_voice_pod(
        operator_id=request.operator_id,
        property_code=request.property_context,  # May be None
    )
    
    # Get response
    response = await voice_pod.chat(request.message)
    
    return WidgetChatResponse(
        response=response.message,
        property_id=request.property_context,
    )


@router.get("/concierge.js")
async def serve_widget_script():
    """Serve the widget JavaScript."""
    from fastapi.responses import Response
    
    widget = WebsiteWidgetV2()
    script = widget.generate_widget_script()
    
    return Response(
        content=script,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        }
    )
'''


# Alternative: Operator-Controlled Property Mapping
class PropertyMappingService:
    """
    Instead of scraping, let operators map their properties.
    
    Dashboard UI:
    1. Operator logs in
    2. Sees list of their properties from PMS
    3. For each property, enters their website URL pattern
    4. Widget knows context from URL matching
    
    This is 100% reliable - no scraping needed.
    """
    
    def __init__(self):
        self._mappings: Dict[str, List[PropertyMapping]] = {}
    
    def add_mapping(
        self,
        operator_id: str,
        website_id: str,
        our_property_id: str,
        url_pattern: str,
    ) -> PropertyMapping:
        """Add a property URL mapping."""
        mapping = PropertyMapping(
            operator_id=operator_id,
            website_property_id=website_id,
            our_property_id=our_property_id,
            page_url_pattern=url_pattern,
        )
        
        if operator_id not in self._mappings:
            self._mappings[operator_id] = []
        self._mappings[operator_id].append(mapping)
        
        return mapping
    
    def find_property(
        self,
        operator_id: str,
        page_url: str,
    ) -> Optional[str]:
        """Find our property ID from a page URL."""
        mappings = self._mappings.get(operator_id, [])
        
        for mapping in mappings:
            # Check if URL matches pattern
            if self._url_matches_pattern(page_url, mapping.page_url_pattern):
                return mapping.our_property_id
            
            # Check if website ID is in URL
            if mapping.website_property_id in page_url:
                return mapping.our_property_id
        
        return None
    
    def _url_matches_pattern(self, url: str, pattern: str) -> bool:
        """Check if URL matches pattern."""
        import re
        
        # Convert pattern to regex
        # /property/{id} -> /property/[^/]+
        regex_pattern = pattern.replace("{id}", "[^/]+")
        regex_pattern = regex_pattern.replace("*", ".*")
        
        try:
            return bool(re.search(regex_pattern, url, re.IGNORECASE))
        except:
            return False
