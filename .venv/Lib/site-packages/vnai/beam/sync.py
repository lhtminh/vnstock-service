"""
Backend Integration Layer
Integrates vnai with the backend vnstock API for:
- Real-time quota verification
- Device management
- Add-on package tracking
- Offline fallback support
"""
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime
log = logging.getLogger(__name__)

class BackendIntegration:
    def __init__(self, backend_url: str ="https://vnstocks.com/api/vnstock"):
        self.backend_url = backend_url
        self.timeout = 5
        self.cache = {}

    def _make_request(self, endpoint: str, api_key: str, method: str ="GET") -> Dict[str, Any]:
        try:
            headers = {
"Authorization":f"Bearer {api_key}",
"Content-Type":"application/json"
            }
            url =f"{self.backend_url}{endpoint}"
            if method =="GET":
                response = requests.get(url, headers=headers, timeout=self.timeout)
            else:
                return {"success": False,"error":f"Unsupported method: {method}"}
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                return {"success": False,"error":"Unauthorized - Invalid API key"}
            elif response.status_code == 404:
                return {"success": False,"error":"Resource not found"}
            else:
                return {"success": False,"error":f"HTTP {response.status_code}"}
        except requests.exceptions.Timeout:
            log.warning(f"Backend API timeout: {endpoint}")
            return {"success": False,"error":"Backend API timeout"}
        except requests.exceptions.ConnectionError:
            log.warning(f"Backend API connection error: {endpoint}")
            return {"success": False,"error":"Backend API connection error"}
        except Exception as e:
            log.warning(f"Backend API error: {e}")
            return {"success": False,"error": str(e)}

    def get_quota_status(self, api_key: str) -> Dict[str, Any]:
        return self._make_request("/quota/status", api_key)

    def get_devices(self, api_key: str) -> Dict[str, Any]:
        return self._make_request("/devices", api_key)

    def get_device_limits(self, api_key: str) -> Dict[str, Any]:
        return self._make_request("/devices/limits", api_key)

    def get_device(self, api_key: str, device_id: str) -> Dict[str, Any]:
        return self._make_request(f"/devices/{device_id}", api_key)

    def get_active_addons(self, api_key: str) -> Dict[str, Any]:
        return self._make_request("/addons/active", api_key)

    def get_complete_metadata(self, api_key: str) -> Dict[str, Any]:
        try:
            quota = self.get_quota_status(api_key)
            devices = self.get_devices(api_key)
            addons = self.get_active_addons(api_key)
            return {
"success": True,
"data": {
"quota": quota.get("data") if quota.get("success") else None,
"devices": devices.get("data") if devices.get("success") else None,
"addons": addons.get("data") if addons.get("success") else None,
"timestamp": datetime.now().isoformat()
                }
            }
        except Exception as e:
            log.warning(f"Failed to get complete metadata: {e}")
            return {"success": False,"error": str(e)}
backend_integration = BackendIntegration()

def get_backend_integration(backend_url: Optional[str] = None) -> BackendIntegration:
    if backend_url:
        return BackendIntegration(backend_url)
    return backend_integration