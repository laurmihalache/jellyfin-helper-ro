"""trailer_manager.py - YouTube-only trailer downloads with validated search"""
import logging
import subprocess
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional, List, Dict

log = logging.getLogger(__name__)

# Minimum score to accept a YouTube result
MIN_SCORE = 5

# Reject videos with these keywords in the title
REJECT_KEYWORDS = frozenset([
    'interview', 'interviu', 'recap', 'review', 'reaction',
    'explained', 'breakdown', 'behind the scenes', 'making of',
    'full movie', 'full episode', 'rezumat', 'episod complet',
])


def _normalize(text: str) -> str:
    """Strip diacritics and lowercase for comparison."""
    nfkd = unicodedata.normalize('NFKD', text)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower()


def _extract_words(text: str) -> set:
    """Extract normalized alphanumeric words from text."""
    return set(re.findall(r'[a-z0-9]+', _normalize(text)))


def _score_candidate(candidate: Dict, title_words: set,
                     year: str = '', is_show: bool = False,
                     is_season: bool = False, season_num: int = 0) -> int:
    """Score a YouTube result. Negative = reject, higher = better.

    Validation uses ALL conditions: title words + year + category.
    """
    video_title = candidate.get('title', '')
    norm_title = _normalize(video_title)
    video_words = _extract_words(video_title)
    duration = candidate.get('duration', 0) or 0
    verified = candidate.get('channel_is_verified', False)

    # --- Hard requirements ---

    # Must contain "trailer"
    if 'trailer' not in video_words:
        return -1

    # Must contain ALL significant words from the original title
    if not title_words.issubset(video_words):
        return -1

    # Reject negative keywords
    for kw in REJECT_KEYWORDS:
        if kw in norm_title:
            return -1

    # For season trailers: must mention the season number
    if is_season and season_num > 0:
        season_pats = [
            f'season {season_num}', f'sezon {season_num}',
            f'sezonul {season_num}', f'sez {season_num}',
            f's{season_num:02d}', f's{season_num} ',
            f'series {season_num}', f'seria {season_num}',
        ]
        if not any(p in norm_title for p in season_pats):
            return -1

    # --- Scoring ---
    score = 5  # Base for passing validation

    # Year match - strong signal of correct movie/show
    if year and year in video_words:
        score += 3

    if verified:
        score += 4

    if 'official' in video_words or 'oficial' in video_words:
        score += 3

    # Prefer red band trailers (uncensored/unrated)
    if 'red' in video_words and 'band' in video_words:
        score += 5

    if 30 <= duration <= 240:
        score += 2
    elif duration > 600:
        score -= 3

    if len(video_words) <= 10:
        score += 1

    return score


class TrailerManager:
    def __init__(self):
        self.stats = {'trailers_downloaded': 0, 'trailers_failed': 0}

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def download_trailer(self, folder: Path, original_title: str,
                         en_title: str, year: str,
                         is_show: bool = False) -> bool:
        """Download trailer via validated YouTube search.

        Args:
            folder: Target folder (trailer.mkv will be saved here)
            original_title: Original language title from TMDB
            en_title: English title from TMDB
            year: Release year
            is_show: True for TV shows, False for movies
        """
        try:
            trailer_path = folder / 'trailer.mkv'
            if trailer_path.exists():
                log.debug(f"Trailer already exists: {folder.name}")
                return True

            log.info(f"Searching YouTube for trailer: {folder.name}")

            yt_url = self._search_youtube_validated(
                original_title=original_title,
                en_title=en_title,
                year=year,
                is_show=is_show,
            )

            if not yt_url:
                log.warning(f"No trailer found for: {folder.name}")
                self.stats['trailers_failed'] += 1
                return False

            log.info(f"Downloading YouTube trailer: {yt_url}")
            if self._download_with_ytdlp(yt_url, trailer_path):
                log.info(f"Downloaded trailer: {folder.name}")
                self.stats['trailers_downloaded'] += 1
                return True
            else:
                log.error(f"YouTube trailer download failed: {yt_url}")
                self.stats['trailers_failed'] += 1
                return False

        except Exception as e:
            log.error(f"Error downloading trailer for {folder}: {e}")
            self.stats['trailers_failed'] += 1
            return False

    def check_season_trailers(self, show_folder: Path,
                              original_name: str, en_name: str):
        """Public: check and download missing season trailers."""
        self._download_season_trailers(show_folder, original_name, en_name)

    # ------------------------------------------------------------------ #
    #  Validated YouTube search                                           #
    # ------------------------------------------------------------------ #

    def _search_youtube_validated(self, original_title: str, en_title: str,
                                  year: str, is_show: bool,
                                  is_season: bool = False,
                                  season_num: int = 0) -> Optional[str]:
        """Search YouTube, validate each result, return best match URL.

        Uses ALL conditions for matching: title words + year + category.
        Prioritises official trailers from verified channels.
        """
        ref_title = original_title if original_title else en_title
        if not ref_title:
            return None

        title_words = _extract_words(ref_title)
        if not title_words:
            return None

        log.info(f"YouTube validated search: ref='{ref_title}', "
                 f"year={year}, type={'show' if is_show else 'movie'}, "
                 f"match_words={title_words}")

        # Build ordered list of search queries
        queries = self._build_queries(original_title, en_title, year,
                                      is_show, is_season, season_num)

        seen_ids: set = set()
        all_candidates: List[Dict] = []
        total_empty = 0

        for qi, query in enumerate(queries):
            if qi > 0:
                time.sleep(2)  # Avoid YouTube rate limiting
            results = self._yt_search_json(query, max_results=10)
            new = 0
            for r in results:
                vid = r.get('id', '')
                if vid and vid not in seen_ids:
                    seen_ids.add(vid)
                    all_candidates.append(r)
                    new += 1
            if not results:
                total_empty += 1
                log.warning(f"yt-dlp returned 0 results for: '{query}'")
            else:
                log.debug(f"Query '{query}': {len(results)} results, {new} new")

            # Early-stop: if we already have a high-confidence match
            best = self._pick_best(all_candidates, title_words,
                                   year, is_show, is_season, season_num)
            if best and best['score'] >= 12:
                log.info(f"Early match (score={best['score']}): "
                         f"'{best['title']}' [{best.get('channel','')}]")
                return f"https://www.youtube.com/watch?v={best['id']}"

        if total_empty == len(queries):
            log.error(f"All {len(queries)} YouTube queries returned 0 results "
                      f"for '{ref_title}' - possible rate limit or network issue")

        # Final pick from all candidates
        best = self._pick_best(all_candidates, title_words,
                               year, is_show, is_season, season_num)
        if best:
            log.info(f"Best match (score={best['score']}): "
                     f"'{best['title']}' [{best.get('channel','')}]")
            return f"https://www.youtube.com/watch?v={best['id']}"

        if all_candidates:
            log.warning(f"Found {len(all_candidates)} YouTube results but "
                        f"none passed validation for '{ref_title}'")
        else:
            log.warning(f"No validated YouTube result for '{ref_title}'")
        return None

    @staticmethod
    def _build_queries(original_title: str, en_title: str, year: str,
                       is_show: bool, is_season: bool,
                       season_num: int) -> List[str]:
        """Build search queries using title + year + category + 'official trailer'.

        Combines all conditions to narrow down results accurately,
        especially for single-word titles or common names.
        Colons are stripped from titles because yt-dlp interprets them
        as URL scheme separators (e.g. 'Underworld: Evolution' fails).
        """
        # Strip colons — yt-dlp treats them as URL scheme delimiters
        en_title = en_title.replace(':', '')
        if original_title:
            original_title = original_title.replace(':', '')

        queries = []
        category = 'tv series' if is_show else 'movie'

        if is_season:
            sn = season_num
            if original_title and original_title != en_title:
                queries.append(
                    f"{original_title} season {sn} official trailer")
            queries.append(
                f"{en_title} season {sn} official trailer")
            if year:
                queries.append(
                    f"{en_title} season {sn} {year} trailer")
        else:
            # Primary: title + year + official trailer
            if year:
                queries.append(
                    f"{en_title} {year} official trailer")
                queries.append(
                    f"{en_title} {year} {category} trailer")
            # Without year
            queries.append(f"{en_title} official trailer")

            # Original title variants (different language)
            if original_title and original_title != en_title:
                if year:
                    queries.append(
                        f"{original_title} {year} official trailer")
                queries.append(f"{original_title} trailer")

        return queries

    def _pick_best(self, candidates: List[Dict], title_words: set,
                   year: str = '', is_show: bool = False,
                   is_season: bool = False,
                   season_num: int = 0) -> Optional[Dict]:
        """Return the highest-scoring candidate above MIN_SCORE."""
        best = None
        best_score = MIN_SCORE - 1

        for c in candidates:
            score = _score_candidate(c, title_words, year, is_show,
                                     is_season, season_num)
            if score > best_score:
                best_score = score
                best = {**c, 'score': score}

        return best

    def _yt_search_json(self, query: str,
                        max_results: int = 10) -> List[Dict]:
        """Run yt-dlp search, return list of dicts with metadata."""
        try:
            cmd = [
                'yt-dlp', '--dump-json',
                '--default-search', f'ytsearch{max_results}',
                '--no-playlist', '--no-download',
                '--js-runtimes', 'node',
                '--remote-components', 'ejs:github',
                query,
            ]
            result = subprocess.run(cmd, capture_output=True,
                                    text=True, timeout=120)
            # Don't check returncode - yt-dlp may return non-zero
            # if some videos fail (age-restricted etc.) but still
            # output valid results to stdout.

            if result.returncode != 0 and not result.stdout.strip():
                stderr_snippet = (result.stderr or '')[:200]
                log.debug(f"yt-dlp exited {result.returncode}: {stderr_snippet}")

            items = []
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    items.append({
                        'id': d.get('id', ''),
                        'title': d.get('title', ''),
                        'channel': d.get('channel', ''),
                        'channel_is_verified': d.get(
                            'channel_is_verified', False),
                        'duration': d.get('duration', 0),
                    })
                except json.JSONDecodeError:
                    continue
            return items

        except subprocess.TimeoutExpired:
            log.warning(f"YouTube search timed out: {query}")
            return []
        except Exception as e:
            log.debug(f"YouTube search error: {e}")
            return []

    # ------------------------------------------------------------------ #
    #  Season trailers                                                    #
    # ------------------------------------------------------------------ #

    def _download_season_trailers(self, show_folder: Path,
                                  original_name: str, en_name: str):
        """Download trailers for individual seasons via YouTube search.
        Skips if only 1 season (show trailer covers it).
        """
        season_folders = [f for f in show_folder.iterdir()
                         if f.is_dir() and f.name.startswith('Season')]

        if not season_folders:
            return

        if not en_name:
            en_name = show_folder.name.split('(')[0].strip()

        seasons_found = 0
        consecutive_misses = 0

        for season_folder in sorted(season_folders):
            try:
                season_num = int(season_folder.name.split()[1])
            except:
                continue

            # Skip Season 01 - show-level trailer covers it
            if season_num == 1:
                continue

            season_trailer = season_folder / 'trailer.mkv'
            if season_trailer.exists():
                log.debug(f"Season {season_num} trailer exists")
                consecutive_misses = 0
                continue

            log.info(f"Searching YouTube for Season {season_num} trailer...")

            yt_url = self._search_youtube_validated(
                original_title=original_name,
                en_title=en_name,
                year='',
                is_show=True,
                is_season=True,
                season_num=season_num,
            )

            if yt_url and self._download_with_ytdlp(yt_url, season_trailer):
                log.info(f"Downloaded Season {season_num} trailer")
                self.stats['trailers_downloaded'] += 1
                seasons_found += 1
                consecutive_misses = 0
            else:
                consecutive_misses += 1
                if consecutive_misses >= 2:
                    log.info(f"No season trailers after {consecutive_misses} "
                             f"consecutive misses - skipping remaining seasons")
                    break

        if seasons_found > 0:
            log.info(f"Downloaded {seasons_found} season trailer(s) "
                     f"for {show_folder.name}")

    # ------------------------------------------------------------------ #
    #  Download helper                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _download_with_ytdlp(url: str, output_path: Path) -> bool:
        """Download video with yt-dlp. Prioritises highest resolution (4K first)."""
        try:
            cmd = [
                'yt-dlp',
                '--format', 'bestvideo+bestaudio/best',
                '--merge-output-format', 'mkv',
                '--output', str(output_path),
                '--no-playlist',
                '--quiet', '--no-warnings',
                '--js-runtimes', 'node',
                '--remote-components', 'ejs:github',
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            return result.returncode == 0 and output_path.exists()

        except subprocess.TimeoutExpired:
            log.error(f"Timeout downloading: {url}")
            return False
        except Exception as e:
            log.error(f"Download error: {e}")
            return False
