"""file_processor.py - Process tagged folders: rename files, create metadata"""
import logging
import re
from pathlib import Path
from typing import Optional, Tuple
from tmdb_client import TMDbClient
from parsers import *
from config import TMDB_API_KEY, VIDEO_EXTENSIONS, SUBTITLE_EXTENSIONS
from metadata_manager import MetadataManager

log = logging.getLogger(__name__)


def _is_latin_text(text: str) -> bool:
    """Check if text uses Latin alphabet (not Hebrew, Arabic, Cyrillic, etc.)"""
    if not text:
        return False
    for char in text:
        code = ord(char)
        if (0x0590 <= code <= 0x05FF or  # Hebrew
            0x0600 <= code <= 0x06FF or  # Arabic
            0x0400 <= code <= 0x04FF or  # Cyrillic
            0x4E00 <= code <= 0x9FFF):   # CJK
            return False
    return True

class FileProcessor:
    def __init__(self, tmdb: TMDbClient):
        self.tmdb = tmdb
        self.metadata = MetadataManager()
        self.stats = {
            'movies_processed': 0,
            'shows_processed': 0,
            'episodes_processed': 0,
            'files_renamed': 0,
            'subtitles_renamed': 0,
            'errors': 0
        }

    def _extract_tmdb_id(self, name: str) -> Optional[str]:
        """Extract TMDB ID from folder name like [tmdb-12345]"""
        match = re.search(r'\[tmdb-(\d+)\]', name)
        return match.group(1) if match else None

    def process_movie_folder(self, folder: Path) -> bool:
        """Process a tagged movie folder - rename video to Romanian title, create metadata.
        Folder must already have [tmdb-ID] in name (tagged by _tag_new_folders).
        Folder name is NOT changed - only video files and subtitles are renamed.
        """
        try:
            tmdb_id = self._extract_tmdb_id(folder.name)

            if not tmdb_id:
                log.debug(f"No TMDB ID in folder name, skipping: {folder.name}")
                return False

            en_data, ro_data = self.tmdb.get_movie_by_id(tmdb_id)

            if not en_data or not ro_data:
                log.warning(f"No TMDB data for: {folder.name}")
                return False

            ro_title = ro_data['title']

            canonical_file_name = sanitize_filename(ro_title)

            changed = False

            # Rename video file to Romanian title
            videos = [f for f in folder.iterdir()
                     if f.suffix.lower() in VIDEO_EXTENSIONS
                     and 'trailer' not in f.name.lower()]
            if videos:
                video = max(videos, key=lambda f: f.stat().st_size)
                new_video_name = f"{canonical_file_name}{video.suffix}"

                if video.name != new_video_name:
                    video.rename(folder / new_video_name)
                    log.info(f"Renamed movie: {new_video_name}")
                    changed = True
                    self.stats['files_renamed'] += 1

                self._process_subtitles(folder, canonical_file_name)

            # Create movie NFO and download poster
            self.metadata.process_movie_metadata(folder)

            if changed:
                self.stats['movies_processed'] += 1

            return changed

        except Exception as e:
            log.error(f"Error processing movie {folder}: {e}")
            self.stats['errors'] += 1
            return False

    def process_show_folder(self, show_folder: Path) -> bool:
        """Process a tagged TV show folder - rename episodes, create metadata.
        Folder must already have [tmdb-ID] in name (tagged by _tag_new_folders).
        Folder name is NOT changed - only episode files are renamed.
        """
        try:
            tmdb_id = self._extract_tmdb_id(show_folder.name)

            if not tmdb_id:
                log.debug(f"No TMDB ID in folder name, skipping: {show_folder.name}")
                return False

            en_data, ro_data = self.tmdb.get_tv_by_id(tmdb_id)

            if not en_data or not ro_data:
                log.warning(f"No TMDB data for: {show_folder.name}")
                return False

            ro_title = ro_data['name']

            changed = False

            # Process episodes in Season folders
            for season_folder in show_folder.iterdir():
                if not season_folder.is_dir() or not season_folder.name.startswith('Season'):
                    continue

                season_num = int(season_folder.name.split()[1])

                for video in season_folder.iterdir():
                    if video.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue

                    _, _, s, e = parse_show_name(video.stem)
                    if s is None or e is None:
                        continue

                    # Get episode title with English fallback
                    episode_title = self._get_episode_title(tmdb_id, s, e)

                    canonical_name = get_canonical_episode_name(ro_title, s, e, episode_title)
                    new_name = f"{canonical_name}{video.suffix}"

                    if video.name != new_name:
                        video.rename(season_folder / new_name)
                        log.info(f"Renamed episode: {new_name}")
                        changed = True
                        self.stats['files_renamed'] += 1

                    self.stats['episodes_processed'] += 1

            # Fetch and save metadata
            self.metadata.process_show_metadata(show_folder)

            # Process subtitles in show root (move to Season folders)
            self._process_show_subtitles(show_folder, show_folder.name)

            if changed:
                self.stats['shows_processed'] += 1

            return changed

        except Exception as e:
            log.error(f"Error processing show {show_folder}: {e}")
            self.stats['errors'] += 1
            return False


    def _find_first_video(self, show_folder: Path) -> Optional[Path]:
        """Find first video file in show"""
        for f in show_folder.iterdir():
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS and 'trailer' not in f.name.lower():
                return f

        for season_folder in show_folder.iterdir():
            if not season_folder.is_dir() or not season_folder.name.startswith('Season'):
                continue
            videos = [f for f in season_folder.iterdir() if f.suffix.lower() in VIDEO_EXTENSIONS]
            if videos:
                return videos[0]

        return None

    def _get_episode_title(self, tmdb_id: str, season: int, episode: int) -> str:
        """Get episode title: Try Romanian, fallback to English, fallback to generic"""
        import requests

        # Try Romanian first
        try:
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}"
            params = {'api_key': TMDB_API_KEY, 'language': 'ro-RO'}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            ro_name = data.get('name', '').strip()
            if ro_name and not ro_name.startswith('Episode ') and not ro_name.startswith('Episodul ') and _is_latin_text(ro_name):
                return ro_name
        except:
            pass

        # Fallback to English
        try:
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}"
            params = {'api_key': TMDB_API_KEY, 'language': 'en-US'}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            en_name = data.get('name', '').strip()
            if en_name and not en_name.startswith('Episode '):
                return en_name
        except:
            pass

        # Final fallback to generic
        return f'Episodul {episode}'

    def _process_subtitles(self, folder: Path, base_name: str):
        """Rename subtitle files"""
        for sub in folder.iterdir():
            if sub.suffix.lower() not in SUBTITLE_EXTENSIONS:
                continue

            if '.en.' in sub.name.lower():
                new_name = f"{base_name}.en{sub.suffix}"
            else:
                new_name = f"{base_name}{sub.suffix}"

            if sub.name != new_name:
                sub.rename(folder / new_name)
                log.info(f"Renamed subtitle: {new_name}")
                self.stats['subtitles_renamed'] += 1

    def _process_show_subtitles(self, show_folder: Path, show_name: str):
        """Move and rename subtitle files for TV shows"""
        try:
            # Find all subtitle files in root show folder
            for sub_file in show_folder.iterdir():
                if not sub_file.is_file():
                    continue
                if sub_file.suffix.lower() not in SUBTITLE_EXTENSIONS:
                    continue

                # Extract S##E## from subtitle filename
                match = re.search(r'[Ss](\d+)[Ee](\d+)', sub_file.name)
                if not match:
                    continue

                season_num = int(match.group(1))
                episode_num = int(match.group(2))

                # Find target season folder
                season_folder = show_folder / f"Season {season_num:02d}"
                if not season_folder.exists():
                    log.warning(f"Season folder not found for {sub_file.name}")
                    continue

                # Find matching video file to get the episode title
                video_pattern = f"*S{season_num:02d}E{episode_num:02d}*"
                video_files = list(season_folder.glob(video_pattern + ".mkv")) + \
                              list(season_folder.glob(video_pattern + ".mp4"))

                if not video_files:
                    log.warning(f"No matching video for {sub_file.name}")
                    continue

                # Use video file's base name for subtitle
                video_file = video_files[0]
                new_sub_name = video_file.stem + sub_file.suffix
                new_sub_path = season_folder / new_sub_name

                # Move and rename
                if sub_file != new_sub_path:
                    sub_file.rename(new_sub_path)
                    log.info(f"Moved & renamed subtitle: Season {season_num:02d}/{new_sub_name}")
                    self.stats['subtitles_renamed'] += 1

        except Exception as e:
            log.error(f"Error processing show subtitles: {e}")
