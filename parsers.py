"""parsers.py - File name parsing utilities with sanitization"""
import re
from typing import Optional, Tuple

def sanitize_filename(name: str) -> str:
    """Remove/replace characters that are invalid in filenames"""
    # Replace colons with dash
    name = name.replace(':', ' -')
    # Remove other invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # Remove multiple spaces
    name = ' '.join(name.split())
    return name.strip()

def parse_movie_name(filename: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract movie title and year from filename"""
    # Remove extension and clean
    name = filename.replace('.mkv', '').replace('.mp4', '').replace('.avi', '')
    name = name.replace('.', ' ').replace('_', ' ')
    
    # Try to find year pattern
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', name)
    if year_match:
        year = year_match.group(1)
        title = name[:year_match.start()].strip()
        # Clean common junk
        title = re.sub(r'\b(1080p|720p|2160p|4K|BluRay|WEB-DL|WEBRip|HDTV|x264|x265|HEVC)\b', '', title, flags=re.IGNORECASE)
        title = ' '.join(title.split())
        return title, year
    
    return name.strip(), None

def parse_show_name(filename: str) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[int]]:
    """Extract show title, year, season, episode from filename"""
    # Remove extension
    name = filename.replace('.mkv', '').replace('.mp4', '').replace('.avi', '')
    name = name.replace('.', ' ').replace('_', ' ')
    
    # Try to find S01E01 pattern
    se_match = re.search(r'[Ss](\d{1,2})[Ee](\d{1,2})', name)
    if not se_match:
        return None, None, None, None
    
    season = int(se_match.group(1))
    episode = int(se_match.group(2))
    
    # Get title before season/episode
    title = name[:se_match.start()].strip()
    
    # Try to find year
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', title)
    year = year_match.group(1) if year_match else None
    if year_match:
        title = title[:year_match.start()].strip()
    
    # Clean junk
    title = re.sub(r'\b(1080p|720p|2160p|4K|BluRay|WEB-DL|WEBRip|HDTV|x264|x265|HEVC)\b', '', title, flags=re.IGNORECASE)
    title = ' '.join(title.split())
    
    return title, year, season, episode


def parse_folder_name(folder_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract title and year from folder name like 'Movie Name (YEAR)'.
    Also works if [tmdb-ID] is already appended."""
    # Strip existing [tmdb-xxx] tag if present
    clean = re.sub(r'\s*\[tmdb-\d+\]', '', folder_name).strip()
    match = re.match(r'^(.+?)\s*\((\d{4})\)\s*$', clean)
    if match:
        return match.group(1).strip(), match.group(2)
    return None, None

def get_canonical_movie_name(title: str, year: str, tmdb_id: str) -> str:
    """Generate canonical movie folder/file name (sanitized)"""
    name = f"{title} ({year}) [tmdb-{tmdb_id}]"
    return sanitize_filename(name)

def get_canonical_show_name(title: str, year: str, tmdb_id: str) -> str:
    """Generate canonical show folder name (sanitized)"""
    name = f"{title} ({year}) [tmdb-{tmdb_id}]"
    return sanitize_filename(name)

def get_canonical_episode_name(show_name: str, season: int, episode: int, episode_title: str) -> str:
    """Generate canonical episode file name (sanitized)"""
    episode_title = sanitize_filename(episode_title)
    name = f"{show_name} - S{season:02d}E{episode:02d} - {episode_title}"
    return sanitize_filename(name)
