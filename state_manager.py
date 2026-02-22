"""state_manager.py - Track processed files"""
import json
import logging
from pathlib import Path
from datetime import datetime
from config import STATE_FILE

log = logging.getLogger(__name__)

class StateManager:
    def __init__(self):
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Load state from file"""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            log.error(f"Failed to load state: {e}")
        return {'processed_files': {}, 'last_scan': None}

    def _save_state(self):
        """Save state to file"""
        try:
            temp_file = STATE_FILE.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            temp_file.replace(STATE_FILE)
        except Exception as e:
            log.error(f"Failed to save state: {e}")

    def is_processed(self, file_path: Path) -> bool:
        """Check if file has been processed"""
        key = str(file_path)
        if key in self.state['processed_files']:
            # Check if file was modified since last processing
            stored_mtime = self.state['processed_files'][key]
            current_mtime = file_path.stat().st_mtime
            return abs(current_mtime - stored_mtime) < 1  # Within 1 second
        return False

    def mark_processed(self, file_path: Path):
        """Mark file as processed"""
        key = str(file_path)
        self.state['processed_files'][key] = file_path.stat().st_mtime
        self._save_state()

    def update_last_scan(self):
        """Update last scan timestamp"""
        self.state['last_scan'] = datetime.now().isoformat()
        self._save_state()

    def get_stats(self) -> dict:
        """Get processing statistics"""
        return {
            'total_processed': len(self.state['processed_files']),
            'last_scan': self.state['last_scan']
        }
