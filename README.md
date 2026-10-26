# pros.gg

Every 2026 pro League of Legends game in one op.gg-style site: player match histories (filters, last-20 summary, form
graph, played-with, lane opponents), champion pages (builds, skill order, full runes, counters, synergy), a tier list by
role and patch, role leaderboards, team and player head-to-heads, multi-search, and game pages with a gold graph,
event timeline and every player's item build order.

## Run it

```
python pipeline/scrape.py      # new games from gol.gg → data/games/<tournament>.json (incremental, ~1.5 req/s)
python pipeline/build.py       # → dist/ (index.html + data/*.json)
cd dist && python -m http.server 8793
```

python pipeline/extras.py --minutes 60   # gold graph, timeline, build/skill order per game (11 requests a game, time-boxed)

`scrape.py --reparse` re-runs the parser over cached pages (cache/, gzipped) without hitting gol.gg.
`scrape.py --only "LCK 2026"` limits to tournaments starting with that name.

## Deploy

`.github/workflows/refresh.yml` scrapes new games every 3 hours, backfills per-game extras for 40 minutes, commits
`data/`, builds and deploys to GitHub Pages. Both scrapers run at 1 request/second and stop on their own if gol.gg stops
responding. Team logos and player photos are hotlinked from the lolesports API.

## Credits

Game data from [Games of Legends (gol.gg)](https://gol.gg); images from Riot's Data Dragon. pros.gg isn't endorsed
by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or
managing Riot Games properties.
