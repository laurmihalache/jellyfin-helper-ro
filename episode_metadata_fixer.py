#!/usr/bin/env python3
"""
Jellyfin Episode Metadata Fixer
Creates NFO files with English titles for episodes that have generic Romanian titles
"""

import re
import time
import requests
from pathlib import Path
from typing import Optional, Dict
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Generic Romanian episode title patterns
GENERIC_PATTERNS = [
    r'^Episodul \d+$',
    r'^Episode \d+$',
    r'^Ep\. \d+$',
    r'^TBA$',
    r'^To Be Announced$',
]

class TMDBMetadataClient:
    """Client for TMDB with Romanian-to-English fallback"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.session = requests.Session()
    
    def is_generic_title(self, title: str) -> bool:
        """Check if title is generic placeholder"""
        if not title:
            return True
        for pattern in GENERIC_PATTERNS:
            if re.match(pattern, title, re.IGNORECASE):
                return True
        return False
    
    def get_episode_metadata(self, tmdb_id: int, season: int, episode: int) -> Optional[Dict]:
        """Get episode metadata with Romanian-to-English fallback"""
        url = f"{self.base_url}/tv/{tmdb_id}/season/{season}/episode/{episode}"
        
        # Try Romanian first
        params = {"api_key": self.api_key, "language": "ro-RO"}
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            ro_data = response.json()
            
            ro_title = ro_data.get("name", "")
            if not self.is_generic_title(ro_title):
                return ro_data
            
            # Fallback to English
            params["language"] = "en-US"
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            print(f"    Error fetching TMDB: {e}")
            return None


class EpisodeMetadataFixer:
    """Fixes episode metadata by creating NFO files"""
    
    def __init__(self, tmdb_api_key: str, tv_shows_path: str):
        self.tmdb = TMDBMetadataClient(tmdb_api_key)
        self.tv_shows_path = Path(tv_shows_path)
        self.stats = {'fixed': 0, 'skipped': 0, 'errors': 0}
    
    def create_episode_nfo(self, video_file: Path, metadata: Dict):
        """Create NFO file for episode"""
        nfo_file = video_file.with_suffix('.nfo')
        
        # Create XML
        root = ET.Element('episodedetails')
        
        ET.SubElement(root, 'title').text = metadata.get('name', '')
        ET.SubElement(root, 'showtitle').text = metadata.get('show_name', '')
        
        if metadata.get('season_number'):
            ET.SubElement(root, 'season').text = str(metadata['season_number'])
        if metadata.get('episode_number'):
            ET.SubElement(root, 'episode').text = str(metadata['episode_number'])
        
        if metadata.get('overview'):
            ET.SubElement(root, 'plot').text = metadata['overview']
        
        if metadata.get('air_date'):
            ET.SubElement(root, 'aired').text = metadata['air_date']
        
        # Pretty print XML
        rough_string = ET.tostring(root, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent="  ")
        
        # Remove XML declaration and extra whitespace
        pretty_xml = '\n'.join([line for line in pretty_xml.split('\n') if line.strip()])
        
        # Write NFO file
        nfo_file.write_text(pretty_xml, encoding='utf-8')
        print(f"    ✓ Created: {nfo_file.name}")
    
    def parse_episode_filename(self, filename: str) -> Optional[Dict]:
        """Parse S01E01 from filename"""
        patterns = [
            r'S(\d+)E(\d+)',
            r's(\d+)e(\d+)',
            r'Season[\s-]*(\d+)[\s-]*Episode[\s-]*(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return {
                    'season': int(match.group(1)),
                    'episode': int(match.group(2))
                }
        return None
    
    def extract_tmdb_id(self, folder_name: str) -> Optional[int]:
        """Extract TMDB ID from folder name like 'Show (2020) [tmdb-12345]'"""
        match = re.search(r'\[tmdb-(\d+)\]', folder_name)
        if match:
            return int(match.group(1))
        return None
    
    def fix_show(self, show_folder: Path):
        """Fix all episodes in a show"""
        tmdb_id = self.extract_tmdb_id(show_folder.name)
        if not tmdb_id:
            print(f"  ⚠ No TMDB ID found in: {show_folder.name}")
            return
        
        # Find all season folders
        season_folders = [f for f in show_folder.iterdir() 
                         if f.is_dir() and re.match(r'Season\s+\d+', f.name, re.IGNORECASE)]
        
        for season_folder in season_folders:
            # Find all video files (skip trailers)
            video_files = []
            for ext in ['.mkv', '.mp4', '.avi', '.m2ts']:
                files = season_folder.glob(f'*{ext}')
                video_files.extend([f for f in files if 'trailer' not in f.name.lower()])
            
            for video_file in video_files:
                self.fix_episode(video_file, tmdb_id, show_folder.name)
    
    def fix_episode(self, video_file: Path, tmdb_id: int, show_name: str):
        """Fix a single episode"""
        # Check if NFO already exists
        nfo_file = video_file.with_suffix('.nfo')
        if nfo_file.exists():
            self.stats['skipped'] += 1
            return
        
        # Parse season/episode from filename
        ep_info = self.parse_episode_filename(video_file.name)
        if not ep_info:
            print(f"  ⚠ Could not parse: {video_file.name}")
            self.stats['errors'] += 1
            return
        
        season = ep_info['season']
        episode = ep_info['episode']
        
        print(f"  S{season:02d}E{episode:02d}: {video_file.name}")
        
        # Get metadata from TMDB
        metadata = self.tmdb.get_episode_metadata(tmdb_id, season, episode)
        if not metadata:
            self.stats['errors'] += 1
            return
        
        title = metadata.get('name', '')
        if self.tmdb.is_generic_title(title):
            print(f"    ⚠ TMDB also has generic title")
            self.stats['skipped'] += 1
            return
        
        # Add show info - FIXED: use show_name parameter, not show_folder
        metadata['show_name'] = show_name.split('[')[0].strip()
        metadata['season_number'] = season
        metadata['episode_number'] = episode
        
        # Create NFO
        self.create_episode_nfo(video_file, metadata)
        self.stats['fixed'] += 1
        
        # Rate limiting
        time.sleep(0.3)
    
    def fix_all(self):
        """Fix all TV shows"""
        print("=" * 80)
        print("Jellyfin Episode Metadata Fixer")
        print("=" * 80)
        print()
        
        if not self.tv_shows_path.exists():
            print(f"TV Shows path not found: {self.tv_shows_path}")
            return
        
        # Get all show folders
        show_folders = [f for f in self.tv_shows_path.iterdir()
                       if f.is_dir() 
                       and not f.name.startswith('.')
                       and not f.name.startswith('#')]
        
        print(f"Found {len(show_folders)} TV shows")
        print()
        
        for idx, show_folder in enumerate(show_folders, 1):
            print(f"[{idx}/{len(show_folders)}] {show_folder.name}")
            self.fix_show(show_folder)
        
        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"NFO files created: {self.stats['fixed']}")
        print(f"Already had NFO: {self.stats['skipped']}")
        print(f"Errors: {self.stats['errors']}")
        print()
