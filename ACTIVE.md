# Rift Ledger — ACTIVE

Last updated: 2026-10-25

## Goal
op.gg-style site for pro play: every 2026 pro game (all leagues on gol.gg, ~8.3k games), public on GitHub Pages
like Worlds Scout (techreign), auto-refreshed.

## How it works
- `pipeline/scrape.py`: gol.gg season S16 tournament list → match lists → per game `page-game` (teams, objectives,
  bans/picks, runes, spells, items, KDA, CS) + `page-fullstats` (60+ stats). Raw pages gzipped in cache/ (not committed);
  parsed games in data/games/<tournament-slug>.json (committed). Failed parses go to `bad` and are skipped after 2 tries.
- `pipeline/build.py`: data/games → dist/data (index.json, p/<pid>, t/<tid>, c/<champ>, g/<tournament>) + Data Dragon refs.
- `src/app.html`: single-file SPA, hash routes: #/ , #/players, #/champions, #/teams, #/tournaments,
  #/player/<id>, #/team/<id>, #/champion/<DDid>, #/game/<tournament>/<gid>, #/t/<tournament>. `?s=lg:LCK` or `?s=t:<slug>` filter.
- Local: `cd dist && python -m http.server 8793` (8790 is taken by Load Bearing).

## Gotchas
- gol.gg shows a stale "stats not updated since 4th April" banner (commented out); data is complete.
- Player rows nest a rune tooltip table: rows are split on the champion-link cell, not matched as <tr>..</tr>.
- Champion icon keys can contain dots (Dr.Mundo). Some pages give only a dragon count (team `dr`), no drake types.

## Status / next
- First full scrape running 2026-10-25 (≈3 h). Then `scrape.py --reparse` (adds `dr` to early games), rebuild, check sizes,
  create repo techreign/rift-ledger, enable Pages (Actions), push.
- Home is an op.gg-style landing (big wordmark + search pill with League select); player left column has op.gg-style
  rank cards (current tournament, season, role rank by KDA) + tournament list above the champion pool.
- Accuracy checked 2026-10-25: per-champion picks/bans match gol.gg exactly for LCK Rounds 1-2, MSI, LPL Split 2.
- Name: user floated "prop.gg" (domain taken + reads like prop bets → fan-policy risk); undecided.
- TODO (user asked to remember): LIFETIME data — all gol.gg seasons back to S3 as an option (not the default view).
  Needs a season dimension in build/app (season select next to League), and a data diet first: 5.3k games = 86 MB already;
  lifetime ≈ 10x games → split index per season, drop duplicated champion rows, maybe shard p/ per season.
- op.gg parity backlog: last-20 summary above match history; match-history filters (champion/role/tournament);
  form/W-L trend graph (LP-graph analogue); "played with" teammates; champion builds (core/boots/runes/spells),
  counters & synergies from lane opponents, tier list by role + patch filter; per-game gold graph / build order /
  objective timeline (gol.gg page-timeline); role leaderboards; head-to-head (team & player); compare/multi-search;
  team logos + player photos (lolesports API); recent searches/favourites (localStorage).
