"""Dota 2 pro matches from the OpenDota API (free tier: 60 calls/min, ~3,000/day).

  python pipeline/dota.py [--since 2026-01-01] [--minutes 20]

1. Lists every pro match since --since (proMatches pages, newest first; later runs stop at the newest one already
   listed) into data/dota/list.json.
2. Fetches full details for premium + professional tier leagues, newest first, into data/dota/m/<match id>.json
   (trimmed to what the site shows). One file per match so bot commits only add files.
3. Caches heroes / items / pro players / teams constants in data/dota/const/ (refreshed weekly).
Stops at the time box or when the day's quota runs low; re-runs continue where it stopped.
"""
import argparse, json, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "dota"
API = "https://api.opendota.com/api/"
TIERS = ("premium", "professional")
left = {"min": 60, "day": 3000}

def get(path):
    for attempt in range(4):
        if left["min"] < 3: time.sleep(61); left["min"] = 60
        try:
            r = urllib.request.urlopen(urllib.request.Request(API + path, headers={"User-Agent": "prostats.gg/0.1"}), timeout=60)
            left["min"] = int(r.headers.get("X-Rate-Limit-Remaining-Minute") or left["min"] - 1)
            left["day"] = int(r.headers.get("X-Rate-Limit-Remaining-Day") or left["day"] - 1)
            return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if int(e.headers.get("X-Rate-Limit-Remaining-Day") or 1) <= 0: raise SystemExit("daily quota used up")
                time.sleep(61); continue
            if e.code == 404: return None
            if attempt == 3: raise
        except Exception:
            if attempt == 3: raise
        time.sleep(3 + 5 * attempt)

# constants are committed (the build needs them on code-only deploys), so keep only the fields the site uses
SLIM = {
    "heroes": lambda d: {k: {f: v.get(f) for f in ("localized_name", "name", "primary_attr", "roles")} for k, v in d.items()},
    "items": lambda d: {k: {f: v.get(f) for f in ("id", "dname", "cost")} for k, v in d.items()},
    "pro_players": lambda d: [{f: p.get(f) for f in ("account_id", "name", "avatarmedium", "country_code", "team_id", "team_name")} for p in d if p.get("name")],
    "teams": lambda d: [{f: t.get(f) for f in ("team_id", "name", "tag", "logo_url")} for t in d],
    "leagues": lambda d: [{f: l.get(f) for f in ("leagueid", "name", "tier")} for l in d if l.get("tier") in ("premium", "professional")],
}

def const(name, path, keep=7 * 86400):
    p = D / "const" / f"{name}.json"
    if not p.exists() or time.time() - p.stat().st_mtime > keep:
        data = get(path)
        if data and name in SLIM: data = SLIM[name](data)
        if data: p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

PF = ("account_id", "name", "personaname", "hero_id", "player_slot", "kills", "deaths", "assists", "last_hits", "denies", "gold_per_min",
      "xp_per_min", "hero_damage", "tower_damage", "hero_healing", "level", "net_worth", "item_0", "item_1", "item_2", "item_3", "item_4",
      "item_5", "item_neutral", "backpack_0", "backpack_1", "backpack_2", "aghanims_scepter", "aghanims_shard", "moonshard", "lane_role",
      "is_roaming", "obs_placed", "sen_placed", "stuns", "camps_stacked", "teamfight_participation", "firstblood_claimed", "multi_kills",
      "kill_streaks", "rune_pickups", "courier_kills", "roshan_kills", "towers_killed", "lane_efficiency_pct")

def trim(m):
    keep = {k: m.get(k) for k in ("match_id", "start_time", "duration", "radiant_win", "radiant_score", "dire_score", "leagueid", "series_id",
            "series_type", "patch", "first_blood_time", "radiant_gold_adv", "radiant_xp_adv", "picks_bans", "region")}
    for side in ("radiant_team", "dire_team"):
        t = m.get(side) or {}
        keep[side] = {k: t.get(k) for k in ("team_id", "name", "tag", "logo_url")}
    keep["league"] = {k: (m.get("league") or {}).get(k) for k in ("leagueid", "name", "tier")}
    keep["players"] = [{k: p.get(k) for k in PF if p.get(k) is not None} for p in m.get("players") or []]
    # build order: completed items worth 1000+ gold, as [minute, item key]
    for p, src in zip(keep["players"], m.get("players") or []):
        buys = [[max(0, x["time"] // 60), x["key"]] for x in src.get("purchase_log") or [] if (ITEMS.get(x.get("key")) or {}).get("cost", 0) >= 1000]
        if buys: p["buys"] = buys
    keep["bv"] = 2  # build-order format: [minute, key], 1000+ gold items only
    return keep

ITEMS = {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--minutes", type=float, default=20)
    a = ap.parse_args()
    stop, t0 = time.time() + a.minutes * 60, int(datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc).timestamp())
    (D / "m").mkdir(parents=True, exist_ok=True)
    leagues = {l["leagueid"]: l for l in const("leagues", "leagues", 86400) or []}
    ITEMS.update(const("items", "constants/items") or {})
    for name, path in (("heroes", "constants/heroes"), ("items", "constants/items"), ("item_ids", "constants/item_ids"),
                       ("pro_players", "proPlayers"), ("teams", "teams")):
        const(name, path)

    lp = D / "list.json"
    known = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else []
    have = {m["match_id"] for m in known}
    newest = max(have) if have else 0
    def walk(below, until):
        """proMatches pages from below match id `below` (None = newest) down to id `until` or the --since date"""
        out, last = [], below
        while time.time() < stop:
            page = get("proMatches" + (f"?less_than_match_id={last}" if last else ""))
            if not page: return out, True
            out += [m for m in page if m["start_time"] >= t0 and m["match_id"] > until and m["match_id"] not in have]
            last = page[-1]["match_id"]
            if page[-1]["start_time"] < t0: return out, True
            if last <= until: return out, False
        return out, False
    fresh, done = walk(None, newest)
    if have and not (D / "list.done").exists():  # an earlier run was cut off before reaching --since
        more, done = walk(min(have), 0); fresh += more
    if done or (D / "list.done").exists(): (D / "list.done").write_text("1")
    known = sorted(known + fresh, key=lambda m: -m["match_id"])
    lp.write_text(json.dumps(known, separators=(",", ":")), encoding="utf-8")
    print(f"listed {len(known)} pro matches since {a.since} (+{len(fresh)})", flush=True)

    tier = lambda m: (leagues.get(m["leagueid"]) or {}).get("tier")
    todo = [m for m in known if tier(m) in TIERS and not (D / "m" / f"{m['match_id']}.json").exists()]
    todo.sort(key=lambda m: (tier(m) != "premium", -m["match_id"]))
    got = 0
    for m in todo:
        if time.time() > stop or left["day"] < 60: break
        d = get(f"matches/{m['match_id']}")
        if d and d.get("players"):
            (D / "m" / f"{m['match_id']}.json").write_text(json.dumps(trim(d), separators=(",", ":")), encoding="utf-8"); got += 1
    print(f"details: +{got}, {len(todo) - got} still to fetch, {left['day']} calls left today")

if __name__ == "__main__":
    main()
