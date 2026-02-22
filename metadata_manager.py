"""Complete metadata management for Jellyfin with Romanian->English fallback"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
import logging
from tmdb_client import TMDbClient
from config import VIDEO_EXTENSIONS
from nfo_generator import create_tvshow_nfo, create_episode_nfo, create_movie_nfo

log = logging.getLogger(__name__)

class MetadataManager:
    def __init__(self):
        self.tmdb = TMDbClient()

    def _extract_tmdb_id(self, folder_name: str) -> Optional[str]:
        """Extract TMDB ID from folder name like [tmdb-12345]"""
        match = re.search(r'\[tmdb-(\d+)\]', folder_name)
        return match.group(1) if match else None

    def _read_nfo_tmdb_id(self, nfo_path: Path) -> Optional[str]:
        """Read the TMDB ID stored inside an existing NFO file"""
        try:
            if not nfo_path.exists():
                return None
            tree = ET.parse(nfo_path)
            root = tree.getroot()
            tmdb_el = root.find('tmdbid')
            if tmdb_el is not None and tmdb_el.text:
                return tmdb_el.text.strip()
        except Exception:
            pass
        return None

    def _needs_metadata_refresh(self, nfo_path: Path, folder_tmdb_id: str) -> bool:
        """Check if metadata needs re-downloading.
        Returns True if:
          - NFO file doesn't exist
          - TMDB ID in NFO doesn't match folder's TMDB ID (folder was renamed)
        """
        if not nfo_path.exists():
            return True
        nfo_tmdb_id = self._read_nfo_tmdb_id(nfo_path)
        if nfo_tmdb_id != folder_tmdb_id:
            if nfo_tmdb_id:
                log.info(f"TMDB ID changed: NFO has {nfo_tmdb_id}, folder has {folder_tmdb_id} - re-downloading metadata")
            return True
        return False

    def process_movie_metadata(self, movie_folder: Path) -> bool:
        """Fetch and save movie metadata with images - skip if up-to-date.
        NFO filename matches the main video file (Romanian title).
        """
        try:
            tmdb_id = self._extract_tmdb_id(movie_folder.name)
            if not tmdb_id:
                return False

            # Find main video to match NFO name to video name
            videos = [f for f in movie_folder.iterdir()
                      if f.suffix.lower() in VIDEO_EXTENSIONS
                      and 'trailer' not in f.name.lower()]
            if videos:
                video = max(videos, key=lambda f: f.stat().st_size)
                nfo_path = video.with_suffix('.nfo')
            else:
                nfo_path = movie_folder / f"{movie_folder.name}.nfo"

            poster_path = movie_folder / "poster.jpg"
            backdrop_path = movie_folder / "backdrop.jpg"

            # Skip if NFO exists with matching TMDB ID and images exist
            if not self._needs_metadata_refresh(nfo_path, tmdb_id) and poster_path.exists():
                return True

            # Get metadata
            en_data, ro_data = self.tmdb.get_movie_by_id(tmdb_id)
            if not ro_data:
                return False

            # Create NFO named to match video file
            create_movie_nfo(ro_data, nfo_path)
            log.info(f"Created movie NFO: {nfo_path.name}")

            # Clean up old NFOs that don't match current video
            for old_nfo in movie_folder.glob('*.nfo'):
                if old_nfo != nfo_path:
                    old_nfo.unlink()
                    log.info(f"Removed stale NFO: {old_nfo.name}")

            # Download poster
            if ro_data.get('poster_path'):
                if self.tmdb.download_image(ro_data['poster_path'], poster_path, 'w500'):
                    log.info(f"Downloaded poster for {movie_folder.name}")

            # Download backdrop
            if ro_data.get('backdrop_path'):
                self.tmdb.download_image(ro_data['backdrop_path'], backdrop_path, 'original')

            return True

        except Exception as e:
            log.error(f"Error processing movie metadata: {e}")
            return False

    def process_show_metadata(self, show_folder: Path) -> bool:
        """Fetch and save TV show metadata with images - skip if up-to-date"""
        try:
            tmdb_id = self._extract_tmdb_id(show_folder.name)
            if not tmdb_id:
                return False

            nfo_path = show_folder / "tvshow.nfo"
            poster_path = show_folder / "poster.jpg"
            backdrop_path = show_folder / "backdrop.jpg"

            # Check if show-level metadata needs refresh
            show_needs_refresh = self._needs_metadata_refresh(nfo_path, tmdb_id) or not poster_path.exists()

            if show_needs_refresh:
                # Get show metadata
                en_data, ro_data = self.tmdb.get_tv_by_id(tmdb_id)
                if not ro_data:
                    return False

                # Create show NFO
                create_tvshow_nfo(ro_data, nfo_path)
                log.info(f"Created tvshow NFO: {show_folder.name}")

                # Download show poster
                if ro_data.get('poster_path'):
                    if self.tmdb.download_image(ro_data['poster_path'], poster_path, 'w500'):
                        log.info(f"Downloaded show poster")

                # Download backdrop
                if ro_data.get('backdrop_path'):
                    self.tmdb.download_image(ro_data['backdrop_path'], backdrop_path, 'original')

            # Process episodes - only those missing NFOs
            for season_folder in show_folder.iterdir():
                if not season_folder.is_dir() or not season_folder.name.startswith('Season'):
                    continue

                match = re.search(r'Season (\d+)', season_folder.name)
                if not match:
                    continue

                season_num = int(match.group(1))
                self._process_season_episodes(show_folder, season_folder, tmdb_id, season_num, show_needs_refresh)

            return True

        except Exception as e:
            log.error(f"Error processing show metadata: {e}")
            return False

    def _process_season_episodes(self, show_folder: Path, season_folder: Path, tmdb_id: str, season_num: int, force_refresh: bool = False):
        """Process metadata for all episodes in a season"""
        for video_file in season_folder.iterdir():
            if video_file.suffix.lower() not in ['.mkv', '.mp4', '.avi']:
                continue

            # Extract episode number from filename
            match = re.search(r'[Ss]\d+[Ee](\d+)', video_file.name)
            if not match:
                continue

            episode_num = int(match.group(1))
            nfo_path = video_file.with_suffix('.nfo')

            # Skip if episode NFO exists and no show-level refresh needed
            if nfo_path.exists() and not force_refresh:
                continue

            # Get episode metadata
            episode_data = self.tmdb.get_episode(tmdb_id, season_num, episode_num)
            if not episode_data:
                continue

            # Create episode NFO
            if create_episode_nfo(episode_data, nfo_path):
                log.info(f"Created NFO: S{season_num:02d}E{episode_num:02d} - {episode_data.get('name')}")

            # Download episode thumbnail
            if episode_data.get('still_path'):
                thumb_path = video_file.with_suffix('.jpg')
                if not thumb_path.exists() or force_refresh:
                    self.tmdb.download_image(episode_data['still_path'], thumb_path, 'w300')
