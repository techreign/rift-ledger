# pros.gg

Every 2026 pro League of Legends game in one op.gg-style site: player match histories (filters, last-20 summary, form
graph, played-with, lane opponents), champion pages (builds, skill order, full runes, counters, synergy), a tier list by
role and patch, role leaderboards, team and player head-to-heads, multi-search, and game pages with a gold graph,
event timeline and every player's item build order.

2026 is the default view. A season picker adds every earlier season on record (2014-2015 and 2020-2025 so far, from
Oracle's Elixir): careers on player and team pages, past-season tier lists, all-time leaderboards and old game pages.

## Run it

```
python pipeline/scrape.py      # new games from gol.gg → data/games/<tournament>.json (incremental, ~1.5 req/s)
python pipeline/build.py       # → dist/ (index.html + data/*.json)
cd dist && python -m http.server 8793
```

python pipeline/extras.py --minutes 60   # gold graph, timeline, build/skill order per game (11 requests a game, time-boxed)

python pipeline/oracle.py ~/dev/oracle-data   # Oracle's Elixir yearly CSVs → data/oe/<year>.json.gz (+ bridge.json)

Past seasons only change when a CSV is added (2016-2019 are still missing: download them from Oracle's Elixir's
Google Drive into the CSV folder and re-run `oracle.py`). The CSVs are too big to commit; data/oe is ~42 MB. build.py
writes those seasons gzipped under dist/data/h (the app inflates them with DecompressionStream) to stay well under
GitHub Pages' 1 GB limit.

`scrape.py --reparse` re-runs the parser over cached pages (cache/, gzipped) without hitting gol.gg.
`scrape.py --only "LCK 2026"` limits to tournaments starting with that name.

## Deploy

`.github/workflows/refresh.yml` scrapes new games every 3 hours, backfills per-game extras for 40 minutes, commits
`data/`, builds and deploys to GitHub Pages. Both scrapers run at 1 request/second and stop on their own if gol.gg stops
responding. Team logos and player photos are hotlinked from the lolesports API.

### Custom domain

1. Buy the domain and add these DNS records at the registrar: `A @` → 185.199.108.153, 185.199.109.153,
   185.199.110.153, 185.199.111.153; `AAAA @` → 2606:50c0:8000::153, 2606:50c0:8001::153, 2606:50c0:8002::153,
   2606:50c0:8003::153; `CNAME www` → techreign.github.io.
2. Repo Settings → Pages → Custom domain: enter it, wait for the DNS check, tick "Enforce HTTPS". (With Actions
   deploys, Pages ignores a CNAME file, so this setting is the only place the domain lives.)
3. Set `SITE` in `pipeline/build.py` to the new address (e.g. `https://pros.gg/`) and push. Share tags, the
   canonical link, robots.txt and sitemap.xml follow it. The data paths are relative, so nothing else changes, and
   the old github.io address redirects to the new domain on its own.

## Credits

2026 game data from [Games of Legends (gol.gg)](https://gol.gg); earlier seasons from
[Oracle's Elixir](https://oracleselixir.com); images from Riot's Data Dragon. pros.gg isn't endorsed
by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or
managing Riot Games properties.
