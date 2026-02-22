"""tmdb_client.py - TMDB API client with validated search and language filtering"""
import requests
import json
import re
import unicodedata
import time
from pathlib import Path
from typing import Optional, Tuple
from config import TMDB_API_KEY, CACHE_FILE

def _is_latin_text(text: str) -> bool:
    """Check if text uses Latin alphabet"""
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


def _normalize_for_compare(text: str) -> str:
    """Strip diacritics and lowercase for title comparison."""
    nfkd = unicodedata.normalize('NFKD', text)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower()


def _title_words(text: str) -> set:
    """Extract normalized words from a title for comparison."""
    return set(re.findall(r'[a-z0-9]+', _normalize_for_compare(text)))


def _find_best_match(results: list, query_title: str, query_year: Optional[str],
                     title_key: str = 'title',
                     date_key: str = 'release_date') -> Optional[dict]:
    """Find the best matching TMDB result by validating ALL conditions:
    - All query title words must appear in the result title
    - Year must match (if provided)

    Falls back to first result if no exact match found.
    """
    if not results:
        return None

    query_words = _title_words(query_title)

    for result in results:
        result_title = result.get(title_key, '')
        result_words = _title_words(result_title)

        # Check year matches
        if query_year:
            result_date = result.get(date_key, '') or ''
            result_year = result_date[:4] if len(result_date) >= 4 else ''
            if result_year != query_year:
                continue

        # Check all query title words appear in result
        if query_words and not query_words.issubset(result_words):
            continue

        return result

    # Fallback: return first result (TMDB relevance ranking)
    return results[0]


class TMDbClient:
    def __init__(self):
        self.api_key = TMDB_API_KEY
        self.base_url = 'https://api.themoviedb.org/3'
        self.cache_file = CACHE_FILE
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text())
            except:
                return {}
        return {}

    def _save_cache(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(self.cache, indent=2))

    def _get_cached(self, key: str) -> Optional[dict]:
        return self.cache.get(key)

    def _set_cached(self, key: str, value: dict):
        self.cache[key] = value
        self._save_cache()

    def _request(self, endpoint: str, params: dict = None, language: str = 'en-US') -> Optional[dict]:
        url = f"{self.base_url}/{endpoint}"
        default_params = {'api_key': self.api_key, 'language': language}
        if params:
            default_params.update(params)

        try:
            response = requests.get(url, params=default_params, timeout=10)
            response.raise_for_status()
            return response.json()
        except:
            return None

    def get_movie_by_id(self, tmdb_id: str) -> Tuple[Optional[dict], Optional[dict]]:
        """Get movie data. Returns (english_data, romanian_or_english_data)"""
        cache_key = f"movie_id:{tmdb_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached.get('en'), cached.get('ro')

        en_data = self._request(f'movie/{tmdb_id}', {'append_to_response': 'videos'}, 'en-US')
        ro_data = self._request(f'movie/{tmdb_id}', {}, 'ro-RO')

        if en_data and ro_data:
            if not _is_latin_text(ro_data.get('title', '')):
                ro_data = en_data

            cache_data = {'en': en_data, 'ro': ro_data}
            self._set_cached(cache_key, cache_data)
            return en_data, ro_data

        return None, None

    def get_tv_by_id(self, tmdb_id: str) -> Tuple[Optional[dict], Optional[dict]]:
        """Get TV show data. Returns (english_data, romanian_or_english_data)"""
        cache_key = f"tv_id:{tmdb_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached.get('en'), cached.get('ro')

        en_data = self._request(f'tv/{tmdb_id}', {'append_to_response': 'videos'}, 'en-US')
        ro_data = self._request(f'tv/{tmdb_id}', {}, 'ro-RO')

        if en_data and ro_data:
            if not _is_latin_text(ro_data.get('name', '')):
                ro_data = en_data

            cache_data = {'en': en_data, 'ro': ro_data}
            self._set_cached(cache_key, cache_data)
            return en_data, ro_data

        return None, None

    def search_movie(self, title: str, year: Optional[str] = None) -> Tuple[Optional[dict], Optional[dict]]:
        """Search for movie. Validates ALL conditions: title words + year + category.
        Returns (english_data, romanian_or_english_data)"""
        cache_key = f"movie_search:{title}:{year}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached.get('en'), cached.get('ro')

        params = {'query': title}
        if year:
            params['year'] = year

        en_results = self._request('search/movie', params, 'en-US')
        ro_results = self._request('search/movie', params, 'ro-RO')

        if en_results and en_results.get('results'):
            # Validate: pick result where title words + year all match
            en_data = _find_best_match(
                en_results['results'], title, year,
                title_key='title', date_key='release_date')

            if not en_data:
                return None, None

            # Find matching ro result by ID
            ro_data = en_data
            if ro_results and ro_results.get('results'):
                for r in ro_results['results']:
                    if r.get('id') == en_data.get('id'):
                        ro_data = r
                        break

            if not _is_latin_text(ro_data.get('title', '')):
                ro_data = en_data

            cache_data = {'en': en_data, 'ro': ro_data}
            self._set_cached(cache_key, cache_data)
            return en_data, ro_data

        return None, None

    def search_tv(self, title: str, year: Optional[str] = None) -> Tuple[Optional[dict], Optional[dict]]:
        """Search for TV show. Validates ALL conditions: title words + year + category.
        Returns (english_data, romanian_or_english_data)"""
        cache_key = f"tv_search:{title}:{year}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached.get('en'), cached.get('ro')

        params = {'query': title}
        if year:
            params['first_air_date_year'] = year

        en_results = self._request('search/tv', params, 'en-US')
        ro_results = self._request('search/tv', params, 'ro-RO')

        if en_results and en_results.get('results'):
            # Validate: pick result where title words + year all match
            en_data = _find_best_match(
                en_results['results'], title, year,
                title_key='name', date_key='first_air_date')

            if not en_data:
                return None, None

            # Find matching ro result by ID
            ro_data = en_data
            if ro_results and ro_results.get('results'):
                for r in ro_results['results']:
                    if r.get('id') == en_data.get('id'):
                        ro_data = r
                        break

            if not _is_latin_text(ro_data.get('name', '')):
                ro_data = en_data

            cache_data = {'en': en_data, 'ro': ro_data}
            self._set_cached(cache_key, cache_data)
            return en_data, ro_data

        return None, None

    def get_episode(self, tmdb_id: str, season: int, episode: int) -> Optional[dict]:
        """Get episode data with Romanian→English fallback"""
        cache_key = f"episode:{tmdb_id}:s{season}e{episode}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        ro_data = self._request(f'tv/{tmdb_id}/season/{season}/episode/{episode}', {}, 'ro-RO')
        en_data = self._request(f'tv/{tmdb_id}/season/{season}/episode/{episode}', {}, 'en-US')

        if not en_data:
            return None

        result = {}
        if ro_data:
            ro_name = ro_data.get('name', '')
            is_generic = bool(re.match(r'^(Episodul|Episode)\s+\d+$', ro_name, re.IGNORECASE))

            if _is_latin_text(ro_name) and not is_generic:
                result['name'] = ro_name
            else:
                result['name'] = en_data.get('name', '')

            result['overview'] = ro_data.get('overview', '') if ro_data.get('overview') else en_data.get('overview', '')
        else:
            result['name'] = en_data.get('name', '')
            result['overview'] = en_data.get('overview', '')

        result['air_date'] = en_data.get('air_date', '')
        result['episode_number'] = en_data.get('episode_number', episode)
        result['season_number'] = en_data.get('season_number', season)
        result['still_path'] = en_data.get('still_path', '')

        self._set_cached(cache_key, result)
        return result

    def download_image(self, image_path: str, save_path: Path, size: str = 'original') -> bool:
        """Download image from TMDB"""
        if not image_path:
            return False

        base_url = 'https://image.tmdb.org/t/p/'
        url = f"{base_url}{size}{image_path}"

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(response.content)
            return True
        except:
            return False
