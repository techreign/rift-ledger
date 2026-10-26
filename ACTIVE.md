# Rift Ledger — ACTIVE

Last updated: 2026-10-26

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
- Live with 6,863 games at first deploy; the Action is filling the rest + extras (builds/timeline backfill ~250 games
  per run → a few days for the season). Champion build sections say "still being collected" until then.
- Accuracy: per-champion picks/bans matched gol.gg exactly for LCK Rounds 1-2, MSI, LPL Split 2.
- Name: user floated "prop.gg" (domain taken; "prop" reads like prop bets → fan-policy risk). Undecided.
- TODO (user asked to remember): LIFETIME data (all gol.gg seasons) as an option, not the default. Needs a season
  dimension + data diet (6.9k games ≈ 120 MB dist already).
