"""jellyfin_scanner.py - Trigger Jellyfin library scans (FIXED)"""
import logging
import requests
from config import JELLYFIN_URL, JELLYFIN_API_KEY

log = logging.getLogger(__name__)

class JellyfinScanner:
    def __init__(self):
        self.url = JELLYFIN_URL
        self.api_key = JELLYFIN_API_KEY

    def trigger_scan(self, library_names: list = None):
        """Trigger library scan for specified libraries"""
        if not self.api_key:
            log.warning("Jellyfin API key not configured, skipping scan")
            return False
        
        try:
            if library_names is None:
                library_names = ['Movies', 'Shows']
            
            # Just trigger a full library refresh
            url = f"{self.url}/Library/Refresh"
            params = {'api_key': self.api_key}
            response = requests.post(url, params=params, timeout=10)
            response.raise_for_status()
            
            log.info(f"Triggered Jellyfin library scan")
            return True
            
        except Exception as e:
            log.error(f"Error triggering Jellyfin scan: {e}")
            return False
