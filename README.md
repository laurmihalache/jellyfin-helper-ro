# Jellyfin Helper RO

Private fork of [jellyfin-helper](https://github.com/YOUR_USERNAME/jellyfin-helper) with **Romanian (`ro-RO`)** hardcoded as the metadata language.

## Differences from Public Version

| Aspect | Public (`jellyfin-helper`) | This repo (`jellyfin-helper-ro`) |
|--------|---------------------------|----------------------------------|
| Language | Configurable via `TMDB_LANGUAGE` | Hardcoded `ro-RO` |
| TMDB returns | `(en_data, local_data)` | `(en_data, ro_data)` |
| Episode fallback | "Episode X" | "Episodul X" |
| Title fix | — | `_fix_show_episode_titles()` replaces generic titles with TMDB Romanian titles |
| Latin text check | — | `_is_latin_text()` validates Romanian titles use Latin characters |
| Trailer reject keywords | English only | + `interviu`, `rezumat`, `episod complet`, `oficial`, `sezon`/`sezonul`/`seria` |
| Dependencies | requests, yt-dlp, python-dotenv | + flask, docker |

## What It Does

Single-run Docker pipeline that scans Movies and TV Shows folders and automatically:

| Step | Movies | TV Shows |
|------|--------|----------|
| **1. TMDB Tag** | Matches folder to TMDB, appends `[tmdb-ID]` | Same |
| **2. Organise** | — | Moves loose episodes into `Season XX/` folders |
| **3. Rename** | Renames video + subtitle files using Romanian TMDB title | Renames episodes to `Show - S01E01 - Romanian Title.ext` |
| **4. Metadata** | Creates `.nfo` + downloads poster & backdrop | Creates show/season NFOs + episode NFOs |
| **5. Trailer** | Downloads official YouTube trailer (up to 4K) | Show trailer + per-season trailers |
| **6. Episode titles** | — | Replaces generic "Episodul X" with actual Romanian episode titles from TMDB |

Every folder is processed independently — errors in one folder never block the rest.

## Setup

### 1. Clone and configure

```bash
git clone <this-repo-url>
cd jellyfin-helper-ro
cp .env.example .env
```

Edit `.env`:

```env
TMDB_API_KEY=your_tmdb_api_key
JELLYFIN_URL=http://your-jellyfin-ip:8096
JELLYFIN_API_KEY=your_jellyfin_api_key
```

### 2. Configure media paths

Edit `docker-compose.yml` volumes to point to your media:

```yaml
volumes:
  - /path/to/your/movies:/media/movies:rw
  - /path/to/your/tv-shows:/media/shows:rw
  - ./data:/app/data:rw
```

### 3. Build and run

```bash
docker compose up --build
```

## Project Structure

```
jellyfin-helper-ro/
├── main.py                    # Pipeline orchestrator (includes _fix_show_episode_titles)
├── config.py                  # Configuration (ro-RO default)
├── tmdb_client.py             # TMDB API client with _is_latin_text()
├── file_processor.py          # File renaming (Romanian "Episodul X" fallback)
├── metadata_manager.py        # NFO + poster + backdrop downloads
├── nfo_generator.py           # XML NFO generators
├── trailer_manager.py         # YouTube trailer search (Romanian reject keywords)
├── episode_metadata_fixer.py  # Episode NFO creation
├── jellyfin_scanner.py        # Jellyfin library scan trigger
├── state_manager.py           # Processing state tracking
├── parsers.py                 # Filename parsing utilities
├── Dockerfile                 # Container image definition
├── docker-compose.yml         # Docker Compose configuration
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
└── .gitignore                 # Git ignore rules
```

## License

Private — not for redistribution.
