# Rift Ledger — ACTIVE

Last updated: 2026-10-26 (2016-19 added, domain prep)

## Goal
op.gg-style site for pro play: every 2026 pro game (all leagues on gol.gg, ~8.3k games). Live at
https://techreign.github.io/rift-ledger/ (repo techreign/rift-ledger), auto-refreshed by a GitHub Action every 3 h.

## How it works
- `pipeline/scrape.py`: gol.gg season S16 → per game `page-game` + `page-fullstats` → data/games/<tournament>.json.
- `pipeline/extras.py`: per game `page-timeline` (gold per player per minute + event log) and `game/ajax.build.php`
  ×10 players (item purchase order, skill order, full runes + shards) → data/extra/<tournament>/<gid>.json
  (one file per game so bot commits only add files). 11 requests/game, time-boxed (`--minutes`).
- Both scrapers: 1 req/s, stop the run after 3 consecutive failed URLs (`Unreachable`).
- `pipeline/build.py`: → dist/data: index.json (players by[t] has 14 stats; team `lo` logos + player `ph` photos
  hotlinked from lolesports getTeams), p/ t/ c/ g/ shards, x/<gid>.json extras, meta.json (tier list cube:
  champ × tournament × patch × role). Data fetches are cache-busted with index `v`.
- `src/app.html` routes: #/ (op.gg-style landing), #/champions (tier list, role + patch), #/players, #/leaderboard,
  #/teams, #/tournaments, #/compare (multi-search), #/player/<id>, #/team/<id>, #/champion/<DDid>, #/game/<t>/<gid>
  (Overview / Gold & timeline / Builds tabs), #/t/<slug>, #/h2h/team/<a>/<b>, #/h2h/player/<a>/<b>.
  Recent searches + favourites in localStorage (rl.recent / rl.fav).
- Local: `cd dist && python -m http.server 8793` (8790 is Load Bearing). dist/phone.html = 390px iframe preview.

## Gotchas
- 2026-10-25: gol.gg started timing out from the home IP after ~4 h at 1.5 req/s (+ extras test). Rate cut to 1.0
  and auto-stop added. Don't scrape locally until it answers again (`curl -m 15 https://gol.gg/robots.txt`).
- gol.gg banner "stats not updated since 4th April" is stale. Player rows nest a rune tooltip table. Champion icon keys
  can contain dots (Dr.Mundo). Some pages only give a dragon count (team `dr`).
- The builds ajax lives at /game/ajax.build.php (base href /game/), POST game_id & player_id (= our pid).

## Status / next
- Launch prep done 2026-10-26: bot commit step rebases before pushing and builds after (data runs deploy latest code;
  code pushes have their own concurrency group so they don't wait behind scrapes); friendly 404/error pages;
  leaderboards + home KDA default to MAJOR leagues (regex MAJOR in app.html, toggle lv=all); OG/Twitter tags +
  static/og.png (pipeline/og.py, re-run after a rename) + favicon; lolesports matching with TEAM_ALIAS, accent folding,
  contains-match (287/307 logos), photos outside a team need name+role (975); home `recent` keeps newest per league.
- First data run (2026-10-26 00:10) was cancelled: it used the old workflow and its push would have been rejected.
  Re-run 40254057792 on the fixed workflow fills the remaining ~1.5k games + 40 min of extras.
- Before sharing: pick the name/domain (prop.gg is taken, reads like betting); ask gol.gg (X: @bynjee / Patreon) for
  their OK; wait ~2 days for build/timeline extras on major leagues.
- Accuracy: per-champion picks/bans matched gol.gg exactly for LCK Rounds 1-2, MSI, LPL Split 2.
- DONE 2026-10-26: lifetime data. pipeline/oracle.py turns Oracle's Elixir CSVs (~/dev/oracle-data, not committed)
  into data/oe/<year>.json.gz + bridge.json (Oracle 2026 ids → names, to link to gol.gg pids). build.py lifetime()
  writes dist/data/h/{index,meta}.json.gz + h/{p,t,c}/<id>.json.gz + g/<old tournament>.json.gz (gzipped; app uses
  DecompressionStream). Old-only ids are 'o'+oracle hex. App: S.season ('' = 2026, 'all', year) via ?y=, header +
  landing + tier-list season selects, loadLife() merges the old index on demand, rowsOf()/shardOf()/metaOf() loaders,
  Seasons card (op.gg past seasons) on player/team pages from index `yrs`. dist ≈ 301 MB.
- 2016-2019 added 2026-10-26 (Drive quota had reset): 93,220 games 2014-2025, dist ≈ 356 MB (Pages limit 1 GB).
  oracle.py writes gzip with mtime=0 so re-runs don't dirty git. build.py LINEAGE merges 17 rebrands (SKT->T1, Samsung->Gen.G,
  Longzhu/Kingzone->DRX, ROX->HLE, Suning->WBG, ...); skipped Misfits->Heretics and MAD Lions KOI->Movistar KOI (Oracle
  ids overlap with concurrent Spanish-league teams). 2026 team pages get yrs season tiles; old game pages explain the
  missing gold/builds tabs.

## 2026-10-26 update
- Renamed to pros.gg (display text, og.png, favicon). Domain not bought; URL unchanged.
- Launch prep: build.py SITE constant drives canonical/og URLs, robots.txt, sitemap.xml. README "Custom domain"
  has the DNS records + Pages steps. Still on the user: pros.gg is taken (registered 2017, Namecheap); pick another (free 2026-10-26: prostats.gg, prosgg.gg, prodb.gg, proledger.gg, prosgg.com), set DNS, Pages custom domain, flip SITE;
  send gol.gg the permission note.

## 2026-10-26 (late): prostats.gg, SEO, ads prep
- User picked **prostats.gg** (pros.gg is taken). Display name/og.png renamed. NOT bought yet: user buys it, sets DNS
  + Pages custom domain, then flip SITE in build.py.
- Path routing replaced hash routing (app rewrites #/ links/hashes to paths; click handler + pushState; BASE from
  <base href>). pipeline/seo.py: app.js/app.css split out, ~9.4k static pages + 404.html shell + full sitemap; first
  load keeps the static SEO title. dist ≈ 460 MB.
- Ads: ADSENSE / AD_SLOT in build.py (env or constant) → meta tags, AdSense script, ads.txt; app placeAd() one unit
  per page. /privacy page + footer link. Waiting on: domain → AdSense application → ids. Then Search Console + sitemap.
- gol.gg permission: user confirmed 2026-10-26 they have it.
- Search Console: URL-prefix property https://techreign.github.io/rift-ledger/ verified 2026-10-26 (HTML meta tag in
  app.html; keep it), sitemap.xml submitted. After the domain move: add a Domain property (DNS TXT) + Change of Address.
- Domain prices seen 2026-10-26: prostats.gg CA$68.98/yr Namecheap, US$51.80 Porkbun. Cheaper free names: prostats.dev,
  prostats.io, prostats.lol, prostatsgg.com. User not signed in to either registrar; purchase is theirs.
