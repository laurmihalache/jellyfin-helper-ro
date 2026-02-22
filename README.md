# Jellyfin Helper RO 🇷🇴

Versiune românească a [jellyfin-helper](https://github.com/laurmihalache/jellyfin-helper) — manager automat de bibliotecă media pentru **Jellyfin**, optimizat pentru utilizatori români.

Containerul Docker scanează folderele de filmé și seriale, apoi automat:

- **Redenumește fișierele video cu titlul românesc** de pe TMDB (cu diacritice corecte)
- **Creează fișiere NFO** cu sinopsis, genuri și anul producției — în română
- **Descarcă poster și fundal** de pe TMDB
- **Descarcă trailer oficial** de pe YouTube (până la 4K), filtrând interviuri, rezumate și recap-uri românești
- **Organizează episoade** în foldere `Season XX/`
- **Redenumește episoadele** în formatul `Serial - S01E01 - Titlu Episod.ext` cu titluri românești
- **Înlocuiește automat** titlurile generice „Episodul X" cu titlurile reale ale episoadelor din TMDB

---

## Ce face — Exemple concrete

### Filme: Înainte și după

```
Înainte:
Movies/
├── Inception (2010)/
│   └── inception.2010.1080p.bluray.mkv

După procesare:
Movies/
├── Inception (2010) [tmdb-27205]/
│   ├── Începutul.mkv                    ← titlu românesc
│   ├── Începutul.nfo                    ← sinopsis + genuri în română
│   ├── poster.jpg
│   ├── backdrop.jpg
│   └── trailer.mkv                     ← trailer oficial YouTube (4K)
```

### Seriale: Înainte și după

```
Înainte:
TV Shows/
├── Breaking Bad (2008)/
│   ├── breaking.bad.s01e01.mkv
│   ├── breaking.bad.s01e02.mkv
│   └── breaking.bad.s02e01.mkv

După procesare:
TV Shows/
├── Breaking Bad (2008) [tmdb-1396]/
│   ├── poster.jpg
│   ├── backdrop.jpg
│   ├── trailer.mkv
│   ├── tvshow.nfo                       ← sinopsis serial în română
│   ├── Season 01/
│   │   ├── Breaking Bad - S01E01 - Pilot.mkv
│   │   ├── Breaking Bad - S01E01 - Pilot.nfo      ← cu titlu și descriere RO
│   │   ├── Breaking Bad - S01E02 - Pisica e în sac.mkv
│   │   └── Breaking Bad - S01E02 - Pisica e în sac.nfo
│   └── Season 02/
│       ├── season02-poster.jpg
│       ├── Breaking Bad - S02E01 - Șapte treizeci și șapte.mkv
│       └── Breaking Bad - S02E01 - Șapte treizeci și șapte.nfo
```

### Filtrare inteligentă a trailerelor

Când caută trailere pe YouTube, versiunea RO respinge automat:
- **Interviuri** (`interviu`)
- **Rezumate** (`rezumat`, `episod complet`)
- **Referințe la sezoane** (`sezon`, `sezonul`, `seria`) — pentru a evita confuzia cu trailere de sezon
- Plus filtrele standard: `review`, `reaction`, `recap`, `full movie`, etc.

### Validare titluri românești

Funcția `_is_latin_text()` verifică automat că titlurile TMDB românești folosesc caractere latine. Dacă TMDB returnează un titlu în alt alfabet (ex: chirilic), se folosește titlul englezesc ca fallback.

---

## Pipeline complet

| Pas | Filme | Seriale |
|-----|-------|---------|
| **1. TMDB Tag** | Identifică filmul pe TMDB, adaugă `[tmdb-ID]` la folder | La fel |
| **2. Organizare** | — | Mută episoadele în foldere `Season XX/` |
| **3. Redenumire** | Video + subtitrări → titlu românesc | Episoade → `Serial - S01E01 - Titlu RO.ext` |
| **4. Metadata** | NFO + poster + backdrop | NFO serial + NFO episoade cu titluri și sinopsis RO |
| **5. Trailer** | Trailer oficial YouTube (până la 4K) | Trailer serial + trailere per sezon |
| **6. Titluri episoade** | — | Înlocuiește „Episodul X" cu titlul real din TMDB |

Fiecare folder se procesează **independent** — o eroare într-un folder nu afectează restul.

Containerul rulează o singură dată, procesează totul, apoi se oprește. Programează-l cu cron sau rulează-l manual.

## Cerințe

- [Docker](https://docs.docker.com/get-docker/) și [Docker Compose](https://docs.docker.com/compose/install/)
- Cheie API [TMDB](https://www.themoviedb.org/settings/api) (gratuită)
- Server [Jellyfin](https://jellyfin.org) cu cheie API

## Instalare

### 1. Clonează și configurează

```bash
git clone <this-repo-url>
cd jellyfin-helper-ro
cp .env.example .env
```

Editează `.env` cu valorile tale:

```env
TMDB_API_KEY=cheia_ta_tmdb
JELLYFIN_URL=http://ip-jellyfin:8096
JELLYFIN_API_KEY=cheia_ta_jellyfin
```

### 2. Configurează căile media

Editează `docker-compose.yml` și actualizează volumele:

```yaml
volumes:
  - /calea/spre/filme:/media/movies:rw
  - /calea/spre/seriale:/media/shows:rw
  - ./data:/app/data:rw
```

### 3. Construiește și rulează

```bash
docker compose up --build
```

### 4. (Opțional) Programare automată

Adaugă un cron job pentru rulare periodică:

```bash
crontab -e
```

Adaugă (rulează zilnic la ora 3):

```
0 3 * * * cd /calea/spre/jellyfin-helper-ro && docker compose up --build >> /var/log/jellyfin-helper-ro.log 2>&1
```

## Configurare

| Variabilă | Obligatoriu | Implicit | Descriere |
|---|---|---|---|
| `TMDB_API_KEY` | **Da** | — | Cheia TMDB ([obține una aici](https://www.themoviedb.org/settings/api)) |
| `JELLYFIN_URL` | **Da** | — | URL server Jellyfin (ex: `http://192.168.1.100:8096`) |
| `JELLYFIN_API_KEY` | **Da** | — | Cheie API Jellyfin (Dashboard → API Keys) |
| `LOG_LEVEL` | Nu | `INFO` | Nivel de logging: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Structura proiectului

```
jellyfin-helper-ro/
├── main.py                    # Orchestrator pipeline (include _fix_show_episode_titles)
├── config.py                  # Configurare (ro-RO implicit)
├── tmdb_client.py             # Client TMDB cu _is_latin_text()
├── file_processor.py          # Redenumire fișiere (fallback „Episodul X")
├── metadata_manager.py        # Descărcare NFO + poster + backdrop
├── nfo_generator.py           # Generatoare XML NFO
├── trailer_manager.py         # Căutare trailere YouTube (filtre românești)
├── episode_metadata_fixer.py  # Creare NFO episoade
├── jellyfin_scanner.py        # Trigger scan bibliotecă Jellyfin
├── state_manager.py           # Urmărire stare procesare
├── parsers.py                 # Utilități parsare nume fișiere
├── Dockerfile                 # Definiție imagine container
├── docker-compose.yml         # Configurare Docker Compose
├── requirements.txt           # Dependențe Python
├── .env.example               # Șablon variabile de mediu
└── .gitignore                 # Reguli git ignore
```

## Diferențe față de versiunea publică

| Aspect | Public (`jellyfin-helper`) | Acest repo (`jellyfin-helper-ro`) |
|--------|---------------------------|-----------------------------------|
| Limbă | Configurabilă via `TMDB_LANGUAGE` | Hardcoded `ro-RO` |
| Titlu episod fallback | "Episode X" | "Episodul X" |
| Fix titluri | — | `_fix_show_episode_titles()` înlocuiește titluri generice |
| Validare text | — | `_is_latin_text()` verifică alphabet latin |
| Filtre trailer | Doar englezești | + `interviu`, `rezumat`, `episod complet`, `sezon`/`seria` |
| Dependențe | requests, yt-dlp, python-dotenv | + flask, docker |

## Depanare

### Nu se descarcă trailere
- Setează `LOG_LEVEL=DEBUG` în `.env` pentru a vedea interogările de căutare
- Filmele vechi sau obscure pot să nu aibă trailere pe YouTube
- După 2 încercări eșuate, titlurile vechi (pre-2000) sunt excluse permanent

### TMDB nu găsește rezultate
- Verifică formatul: `Titlu (An)` pentru foldere
- Verifică cheia TMDB

### Scanarea Jellyfin nu se declanșează
- Verifică că `JELLYFIN_URL` este accesibil din container
- Verifică permisiunile cheii API

## Licență

Privat — nu pentru redistribuire.

## Mulțumiri

- [Jellyfin](https://jellyfin.org) — Sistemul media open-source
- [TMDB](https://www.themoviedb.org) — The Movie Database API
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — Descărcător video YouTube
