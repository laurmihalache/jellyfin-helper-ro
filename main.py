"""main.py - Per-folder pipeline: tag → rename → metadata → trailer.

Each media folder is processed independently through the full pipeline.
Errors in one folder never prevent processing of the next.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional

from tmdb_client import TMDbClient
from file_processor import FileProcessor
from trailer_manager import TrailerManager
from jellyfin_scanner import JellyfinScanner
from state_manager import StateManager
from config import (MOVIES_PATH, SHOWS_PATH, LOG_LEVEL, VIDEO_EXTENSIONS,
                    TMDB_API_KEY, TRAILER_FAILURES_FILE, TRAILER_MAX_ATTEMPTS)
from parsers import (parse_show_name, parse_folder_name,
                     get_canonical_episode_name, sanitize_filename)
from episode_metadata_fixer import EpisodeMetadataFixer
from metadata_manager import MetadataManager

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Trailer failure tracking (persistent across runs)                   #
# ------------------------------------------------------------------ #

def _load_trailer_failures() -> dict:
    """Load trailer failure counts from persistent JSON file."""
    if TRAILER_FAILURES_FILE.exists():
        try:
            return json.loads(TRAILER_FAILURES_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Could not load trailer failures: {e}")
    return {}


def _save_trailer_failures(failures: dict):
    """Persist trailer failure counts to JSON."""
    try:
        TRAILER_FAILURES_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRAILER_FAILURES_FILE.write_text(
            json.dumps(failures, indent=2, ensure_ascii=False))
    except OSError as e:
        log.error(f"Could not save trailer failures: {e}")


def _is_trailer_excluded(failures: dict, tmdb_id: str) -> bool:
    """Check if a TMDB ID is permanently excluded from trailer search."""
    key = f"tmdb-{tmdb_id}"
    entry = failures.get(key, {})
    return entry.get('excluded', False)


def _record_trailer_failure(failures: dict, tmdb_id: str, name: str):
    """Increment failure count. Mark excluded if >= TRAILER_MAX_ATTEMPTS."""
    key = f"tmdb-{tmdb_id}"
    entry = failures.get(key, {'count': 0, 'name': name, 'excluded': False})
    entry['count'] = entry.get('count', 0) + 1
    entry['name'] = name
    if entry['count'] >= TRAILER_MAX_ATTEMPTS:
        entry['excluded'] = True
        log.info(f"Permanently excluding '{name}' from trailer search "
                 f"(failed {entry['count']} times)")
    failures[key] = entry


def _record_trailer_success(failures: dict, tmdb_id: str):
    """Remove from failure tracking on success."""
    key = f"tmdb-{tmdb_id}"
    if key in failures:
        del failures[key]


def _extract_year_from_folder(name: str) -> int:
    """Extract release year from folder name like 'Title (2006) [tmdb-XXX]'.
    Returns 0 if no year found."""
    m = re.search(r'\((\d{4})\)', name)
    return int(m.group(1)) if m else 0


# Only permanently exclude items released before this year.
# Newer content almost certainly has trailers on YouTube.
EXCLUSION_YEAR_CUTOFF = 2000


# ------------------------------------------------------------------ #
#  Main class                                                          #
# ------------------------------------------------------------------ #

class JellyfinHelper:
    def __init__(self):
        self.tmdb = TMDbClient()
        self.processor = FileProcessor(self.tmdb)
        self.trailer_mgr = TrailerManager()
        self.jellyfin = JellyfinScanner()
        self.state = StateManager()
        self.metadata = MetadataManager()
        self.metadata_fixer = EpisodeMetadataFixer(
            tmdb_api_key=TMDB_API_KEY,
            tv_shows_path=str(SHOWS_PATH)
        )

    # ============================================================== #
    #  Entry point                                                     #
    # ============================================================== #

    def run_once(self):
        """Process every media folder through the full pipeline, then exit."""
        log.info("=" * 60)
        log.info("Jellyfin Helper - Single Run Mode")
        log.info("=" * 60)

        # Clear state for fresh scan
        from config import STATE_FILE
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            log.info("Cleared previous state - starting fresh scan")
            self.state = StateManager()

        failures = _load_trailer_failures()
        excluded_count = sum(1 for v in failures.values()
                            if v.get('excluded'))
        if excluded_count:
            log.info(f"Trailer exclusions: {excluded_count} item(s)")

        changes = False
        errors = 0

        # ---- Movies (each folder: tag → rename → metadata → trailer) ----
        if MOVIES_PATH.exists():
            movies = sorted(
                f for f in MOVIES_PATH.iterdir()
                if f.is_dir() and not f.name.startswith(('.', '#', '@'))
            )
            log.info(f"Processing {len(movies)} movie folder(s)...")
            for folder in movies:
                try:
                    if self._process_movie(folder, failures):
                        changes = True
                except Exception as e:
                    errors += 1
                    log.error(f"[MOVIE] '{folder.name}': {e}")

        # ---- Shows (each folder: tag → organise → rename → metadata →
        #             trailer → episode titles → episode NFOs) ----
        if SHOWS_PATH.exists():
            shows = sorted(
                f for f in SHOWS_PATH.iterdir()
                if f.is_dir() and not f.name.startswith(('.', '#', '@'))
            )
            log.info(f"Processing {len(shows)} show folder(s)...")
            for folder in shows:
                try:
                    if self._process_show(folder, failures):
                        changes = True
                except Exception as e:
                    errors += 1
                    log.error(f"[SHOW] '{folder.name}': {e}")

        # ---- Persist & finish ----
        _save_trailer_failures(failures)

        if changes:
            self.jellyfin.trigger_scan()

        self.state.update_last_scan()

        log.info("=" * 60)
        if errors:
            log.info(f"Scan complete — {errors} folder(s) had errors")
        else:
            log.info("Scan complete")
        log.info("=" * 60)

    # ============================================================== #
    #  Per-movie pipeline                                              #
    # ============================================================== #

    def _process_movie(self, folder: Path, failures: dict) -> bool:
        """Tag → rename files → metadata → trailer for ONE movie folder.

        Returns True if any files were changed (for Jellyfin rescan).
        """
        # 1. Tag with TMDB ID if needed
        if '[tmdb-' not in folder.name:
            folder = self._tag_folder(folder, is_movie=True)
            if not folder:
                return False

        changed = False

        # 2. Rename files + metadata
        videos = [f for f in folder.iterdir()
                  if f.suffix.lower() in VIDEO_EXTENSIONS
                  and 'trailer' not in f.name.lower()]

        if videos:
            video = max(videos, key=lambda f: f.stat().st_size)
            if not self.state.is_processed(video):
                if self.processor.process_movie_folder(folder):
                    changed = True
                # Re-find after possible rename
                videos = [f for f in folder.iterdir()
                          if f.suffix.lower() in VIDEO_EXTENSIONS
                          and 'trailer' not in f.name.lower()]
                if videos:
                    self.state.mark_processed(
                        max(videos, key=lambda f: f.stat().st_size))
        else:
            # No video files yet — just ensure metadata exists
            self.metadata.process_movie_metadata(folder)

        # 3. Trailer
        self._handle_trailer(folder, failures, is_show=False)

        return changed

    # ============================================================== #
    #  Per-show pipeline                                               #
    # ============================================================== #

    def _process_show(self, folder: Path, failures: dict) -> bool:
        """Tag → organise → rename → metadata → trailer → titles → NFOs
        for ONE show folder.

        Returns True if any files were changed (for Jellyfin rescan).
        """
        # 1. Tag with TMDB ID if needed
        if '[tmdb-' not in folder.name:
            folder = self._tag_folder(folder, is_movie=False)
            if not folder:
                return False

        match = re.search(r'\[tmdb-(\d+)\]', folder.name)
        if not match:
            return False
        tmdb_id = match.group(1)

        changed = False

        # 2. Organise loose episodes into Season folders
        self._organize_episodes(folder)

        # 3. Rename episodes + metadata
        has_videos = False
        needs_processing = False
        for season_folder in folder.iterdir():
            if not season_folder.is_dir():
                continue
            if not season_folder.name.startswith('Season'):
                continue
            for video in season_folder.iterdir():
                if video.suffix.lower() in VIDEO_EXTENSIONS:
                    has_videos = True
                    if not self.state.is_processed(video):
                        needs_processing = True
                        break
            if needs_processing:
                break

        if has_videos:
            if needs_processing:
                if self.processor.process_show_folder(folder):
                    changed = True
            # Mark all videos as processed
            for season_folder in folder.iterdir():
                if (season_folder.is_dir()
                        and season_folder.name.startswith('Season')):
                    for video in season_folder.iterdir():
                        if video.suffix.lower() in VIDEO_EXTENSIONS:
                            self.state.mark_processed(video)
        else:
            # No video files yet — just ensure metadata exists
            self.metadata.process_show_metadata(folder)

        # 4. Trailer (show-level + season trailers)
        self._handle_trailer(folder, failures, is_show=True)

        en_data, _ = self.tmdb.get_tv_by_id(tmdb_id)
        if en_data:
            original_name = (en_data.get('original_name', '')
                             or en_data.get('name', ''))
            en_name = en_data.get('name', '')
            self.trailer_mgr.check_season_trailers(
                folder, original_name, en_name)

        # 5. Fix episode titles (generic "Episodul X" → proper title)
        try:
            self._fix_show_episode_titles(folder, tmdb_id)
        except Exception as e:
            log.error(f"  Episode title fix error for '{folder.name}': {e}")

        # 6. Episode NFOs
        try:
            self.metadata_fixer.fix_show(folder)
        except Exception as e:
            log.error(f"  Episode NFO error for '{folder.name}': {e}")

        return changed

    # ============================================================== #
    #  Shared helpers                                                  #
    # ============================================================== #

    def _tag_folder(self, folder: Path, is_movie: bool) -> Optional[Path]:
        """Parse folder name, search TMDB, append [tmdb-ID].

        Returns the new Path on success, None if it cannot be tagged.
        """
        title, year = parse_folder_name(folder.name)
        if not title:
            log.debug(f"Cannot parse folder name: {folder.name}")
            return None

        media_type = 'movie' if is_movie else 'TV show'
        search_fn = (self.tmdb.search_movie if is_movie
                     else self.tmdb.search_tv)

        log.info(f"New {media_type} detected: '{title}' ({year})")

        en_data, _ = search_fn(title, year)
        if not en_data:
            log.warning(f"No TMDB match for {media_type}: {folder.name}")
            return None

        tmdb_id = str(en_data['id'])
        matched_title = en_data.get('title', en_data.get('name', ''))

        # For non-English productions, include original title
        orig_lang = en_data.get('original_language', 'en')
        orig_title = en_data.get('original_title',
                                 en_data.get('original_name', ''))

        if (orig_lang != 'en' and orig_title
                and orig_title != matched_title):
            safe_orig = sanitize_filename(orig_title)
            new_name = f"{title} ({safe_orig}) ({year}) [tmdb-{tmdb_id}]"
        else:
            new_name = f"{folder.name} [tmdb-{tmdb_id}]"

        new_path = folder.parent / new_name
        if new_path.exists():
            log.warning(f"Target folder already exists: {new_name}")
            return None

        folder.rename(new_path)
        log.info(f"Tagged: {new_name} (TMDB: {matched_title})")
        return new_path

    # ---- Trailer with failure tracking ---- #

    def _handle_trailer(self, folder: Path, failures: dict,
                        is_show: bool):
        """Download trailer for a folder, respecting exclusion rules."""
        if (folder / 'trailer.mkv').exists():
            return

        match = re.search(r'\[tmdb-(\d+)\]', folder.name)
        if not match:
            return

        tmdb_id = match.group(1)
        year = _extract_year_from_folder(folder.name)

        # Only pre-2000 content can be permanently excluded
        if year and year < EXCLUSION_YEAR_CUTOFF:
            if _is_trailer_excluded(failures, tmdb_id):
                log.debug(f"Skipping excluded trailer: {folder.name}")
                return

        if is_show:
            success = self._download_show_trailer(folder)
        else:
            success = self._download_movie_trailer(folder)

        if success:
            _record_trailer_success(failures, tmdb_id)
        elif year and year < EXCLUSION_YEAR_CUTOFF:
            _record_trailer_failure(failures, tmdb_id, folder.name)

    def _download_movie_trailer(self, folder: Path) -> bool:
        """Download movie trailer. Returns True on success."""
        try:
            match = re.search(r'\[tmdb-(\d+)\]', folder.name)
            if not match:
                return False

            tmdb_id = match.group(1)
            en_data, _ = self.tmdb.get_movie_by_id(tmdb_id)

            if not en_data:
                return False

            original_title = (en_data.get('original_title', '')
                              or en_data.get('title', ''))
            en_title = en_data.get('title', '')
            year = (en_data.get('release_date', '') or '')[:4]

            return self.trailer_mgr.download_trailer(
                folder, original_title, en_title, year, is_show=False)
        except Exception as e:
            log.debug(f"Could not download movie trailer: {e}")
            return False

    def _download_show_trailer(self, folder: Path) -> bool:
        """Download show trailer. Returns True on success."""
        try:
            match = re.search(r'\[tmdb-(\d+)\]', folder.name)
            if not match:
                return False

            tmdb_id = match.group(1)
            en_data, _ = self.tmdb.get_tv_by_id(tmdb_id)

            if not en_data:
                return False

            original_name = (en_data.get('original_name', '')
                             or en_data.get('name', ''))
            en_name = en_data.get('name', '')
            year = (en_data.get('first_air_date', '') or '')[:4]

            return self.trailer_mgr.download_trailer(
                folder, original_name, en_name, year, is_show=True)
        except Exception as e:
            log.debug(f"Could not download show trailer: {e}")
            return False

    # ---- Organise loose episodes ---- #

    def _organize_episodes(self, show_folder: Path):
        """Move loose video files in show root into Season folders."""
        loose = [f for f in show_folder.iterdir()
                 if f.is_file()
                 and f.suffix.lower() in VIDEO_EXTENSIONS
                 and 'trailer' not in f.name.lower()]
        if not loose:
            return

        log.info(f"  {len(loose)} loose episode(s) to organise")
        for video in loose:
            try:
                _, _, season, _ = parse_show_name(video.stem)
                if season is None:
                    continue
                season_folder = show_folder / f"Season {season:02d}"
                if not season_folder.exists():
                    season_folder.mkdir()
                target = season_folder / video.name
                if not target.exists():
                    video.rename(target)
                    log.info(f"  Moved to {season_folder.name}: {video.name}")
            except Exception as e:
                log.error(f"  Error organising {video.name}: {e}")

    # ---- Fix episode titles ---- #

    def _fix_show_episode_titles(self, show_folder: Path, tmdb_id: str):
        """Replace generic 'Episodul X' titles with proper TMDB titles."""
        _, ro_data = self.tmdb.get_tv_by_id(tmdb_id)
        if not ro_data:
            return

        ro_title = ro_data['name']
        updated = 0

        for season_folder in show_folder.iterdir():
            if not season_folder.is_dir():
                continue
            if not season_folder.name.startswith('Season'):
                continue

            for video in season_folder.iterdir():
                if (video.suffix.lower() not in VIDEO_EXTENSIONS
                        or 'trailer' in video.name.lower()):
                    continue

                _, _, s, e = parse_show_name(video.stem)
                if s is None or e is None:
                    continue

                if f'Episodul {e}' not in video.stem:
                    continue

                proper_title = self.processor._get_episode_title(
                    tmdb_id, s, e)
                if proper_title and proper_title != f'Episodul {e}':
                    canonical = get_canonical_episode_name(
                        ro_title, s, e, proper_title)
                    new_name = f"{canonical}{video.suffix}"
                    if video.name != new_name:
                        video.rename(season_folder / new_name)
                        log.info(f"  Updated episode: {new_name}")
                        updated += 1

        if updated:
            log.info(f"  Updated {updated} episode title(s)")


if __name__ == '__main__':
    helper = JellyfinHelper()
    helper.run_once()
