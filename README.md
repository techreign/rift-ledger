# prostats.gg

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
3. Set `SITE` in `pipeline/build.py` to the new address (`https://prostats.gg/`) and push. `<base href>`, share
   tags, canonical links, robots.txt and sitemap.xml all follow it, and the old github.io address redirects to the
   new domain on its own.

### Search (SEO)

The app routes on real paths (`player/48/`, `team/2809/`, `champion/Azir/`, `t/<slug>/`); old `#/` links are
rewritten in place. `pipeline/seo.py` writes a static `index.html` for every 2026 player/team, every older player/team
with 30+ games, every champion and tournament (~9.4k pages): its own title, description, canonical, JSON-LD and a
plain-HTML summary with links, which the app replaces once it loads. Other paths (games, h2h, filters) fall through to
`404.html`, the same app shell. Local test of the path routing: `SITE=http://127.0.0.1:8794/ python pipeline/build.py`,
then serve `dist` with a server that answers missing paths with 404.html.

After the domain is live: add it to [Google Search Console](https://search.google.com/search-console) as a Domain
property (DNS TXT record), submit `https://prostats.gg/sitemap.xml`, and do the same in Bing Webmaster Tools.

### Ads

1. Apply at [AdSense](https://adsense.google.com) with the custom domain (github.io subdomains aren't accepted).
2. Set `ADSENSE = "ca-pub-..."` in `pipeline/build.py` (or the `ADSENSE` env var in the workflow) and push: that adds
   the verification tag, the AdSense script and `ads.txt`, which AdSense checks during review.
3. After approval, in AdSense: turn on the GDPR/US-state consent messages (Privacy & messaging; required for EEA/UK
   visitors), create one responsive display ad unit, and set its id as `AD_SLOT`. The app then puts one unit per
   page: bottom of the sidebar on profile pages, under the content elsewhere, never on error or privacy pages.

## Credits

2026 game data from [Games of Legends (gol.gg)](https://gol.gg); earlier seasons from
[Oracle's Elixir](https://oracleselixir.com); images from Riot's Data Dragon. prostats.gg isn't endorsed
by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or
managing Riot Games properties.
