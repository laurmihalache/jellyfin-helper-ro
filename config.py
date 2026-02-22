import os
from pathlib import Path

# Jellyfin Configuration
JELLYFIN_URL = os.getenv('JELLYFIN_URL', '')
JELLYFIN_API_KEY = os.getenv('JELLYFIN_API_KEY', '')

# TMDB Configuration
TMDB_API_KEY = os.getenv('TMDB_API_KEY', '')
TMDB_LANGUAGE = os.getenv('TMDB_LANGUAGE', 'ro-RO')
TMDB_CACHE_DAYS = 180

# Paths
DATA_DIR = Path('/app/data')
CACHE_FILE = DATA_DIR / 'tmdb_cache.json'
STATE_FILE = DATA_DIR / 'state.json'
TRAILER_FAILURES_FILE = DATA_DIR / 'trailer_failures.json'
TRAILER_MAX_ATTEMPTS = 2

# Media paths (from docker volumes)
MOVIES_PATH = Path('/media/movies')
SHOWS_PATH = Path('/media/shows')

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Video extensions
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.m4v', '.ts', '.m2ts'}

# Subtitle extensions
SUBTITLE_EXTENSIONS = {'.srt', '.sub', '.ass', '.ssa', '.vtt'}
