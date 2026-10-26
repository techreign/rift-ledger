"""Build the static site: dist/index.html + dist/data/*.json from data/games/*.json.

Outputs (all fetched lazily by the app):
  data/index.json         tournaments, players, teams, champions (with per-tournament counts), recent games, Data Dragon refs
  data/p/<pid>.json       a player's match history
  data/t/<tid>.json       a team's games
  data/c/<champ>.json     every pro pick of a champion
  data/g/<tournament>.json  full game details (scoreboard + all stats), keyed by game id
  data/x/<game>.json      per-game extras (gold per minute, event log, build/skill order, full runes) when scraped
  data/meta.json          champion picks/wins by tournament x patch x role (+ bans) for the tier list
"""
import json, re, shutil, sys, time, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST, OUT = ROOT / "dist", ROOT / "dist" / "data"
CACHE = ROOT / "cache"

def get_json(url, name):
    p = CACHE / name
    if not p.exists():
        p.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "RiftLedger/0.1"}), timeout=60).read())
    return json.loads(p.read_text(encoding="utf-8"))

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def league_of(name):
    return re.sub(r"\s*\b2026\b.*$", "", name).strip() or re.sub(r"^2026\s*", "", name).strip()
def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
ROLES = ["top", "jungle", "mid", "adc", "support"]

def ddragon():
    CACHE.mkdir(exist_ok=True)
    ver = json.loads(urllib.request.urlopen("https://ddragon.leagueoflegends.com/api/versions.json", timeout=60).read())[0]
    champs = get_json(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json", f"dd_champ_{ver}.json")["data"]
    items = get_json(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/item.json", f"dd_item_{ver}.json")["data"]
    runes = get_json(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/runesReforged.json", f"dd_runes_{ver}.json")
    rmap = {}
    for st in runes:
        rmap[st["id"]] = [st["name"], st["icon"]]
        for slot in st["slots"]:
            for r in slot["runes"]: rmap[r["id"]] = [r["name"], r["icon"]]
    # "big" items: finished items worth showing in build summaries (not components, boots tier 1, consumables, trinkets)
    big = [int(i) for i, it in items.items() if it.get("gold", {}).get("total", 0) >= 2000 and not it.get("into") and it.get("gold", {}).get("purchasable")]
    boots = [int(i) for i, it in items.items() if "Boots" in it.get("tags", []) and it.get("depth", 1) >= 2]
    return dict(ver=ver, champs={c["name"]: [c["id"], c["name"]] for c in champs.values()},
                items={int(i): it["name"] for i, it in items.items()}, big=sorted(set(big + boots)), boots=sorted(boots), runes=rmap)

LOL_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"  # public key the lolesports.com site itself ships
def lolesports():
    """Team logos + player photos from the lolesports API (hotlinked, not downloaded). Cached for a week."""
    p = CACHE / "lol_teams.json"
    if not p.exists() or time.time() - p.stat().st_mtime > 7 * 86400:
        try:
            req = urllib.request.Request("https://esports-api.lolesports.com/persisted/gw/getTeams?hl=en-US", headers={"x-api-key": LOL_KEY, "User-Agent": "RiftLedger/0.1"})
            p.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        except Exception as e:
            print("lolesports fetch failed:", e, file=sys.stderr)
            if not p.exists(): return {}, {}, {}
    teams = json.loads(p.read_text(encoding="utf-8"))["data"]["teams"]
    teams.sort(key=lambda t: t.get("status") != "active")  # active teams win name clashes
    https = lambda u: (u or "").replace("http://", "https://")
    logo, roster, anyp = {}, {}, defaultdict(list)
    for t in teams:
        k = norm(t["name"])
        if k and k not in logo and t.get("image"): logo[k] = https(t["image"]); roster[k] = {}
        for pl in t.get("players") or []:
            img = https(pl.get("image"))
            if not img or "default-headshot" in img: continue
            if k in roster: roster[k].setdefault(norm(pl["summonerName"]), img)
            anyp[norm(pl["summonerName"])].append(img)
    return logo, roster, {k: v[0] for k, v in anyp.items() if len(set(v)) == 1}

def max_order(sk):
    """'QEWQQRQ...' -> 'QEW' (most points first, ties by who got there first)"""
    if not sk: return None
    first, cnt = {}, {"Q": 0, "W": 0, "E": 0}
    for i, c in enumerate(sk[:18]):
        if c in cnt: cnt[c] += 1; first[(c, cnt[c])] = i
    return "".join(sorted(cnt, key=lambda c: (-cnt[c], first.get((c, cnt[c]), 99))))

def main():
    dd = ddragon()
    by_norm = {norm(n): v for n, v in dd["champs"].items()} | {norm(v[0]): v for v in dd["champs"].values()}
    champ_id = {}  # gol.gg display name -> Data Dragon id
    def cid(display, golkey=None):
        if display not in champ_id:
            hit = by_norm.get(norm(display)) or (by_norm.get(norm(golkey)) if golkey else None)
            champ_id[display] = hit[0] if hit else (golkey or re.sub(r"[^A-Za-z]", "", display))
        return champ_id[display]

    logo, roster, anyp = lolesports()
    boots, big = set(dd["boots"]), set(dd["big"])
    extras, xdir = {}, ROOT / "data" / "extra"
    for f in xdir.glob("*/*.json") if xdir.exists() else []:
        extras[f.stem] = json.loads(f.read_text(encoding="utf-8"))

    tours, games = [], []
    for f in sorted((ROOT / "data" / "games").glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        if not doc["games"]: continue
        s = f.stem; gs = sorted(doc["games"].values(), key=lambda g: (g["date"] or "", g["id"]))
        tours.append(dict(s=s, n=doc["name"], lg=league_of(doc["name"]), rg=doc.get("region"), g=len(gs), a=gs[0]["date"], b=gs[-1]["date"]))
        for g in gs: g["t"] = s; games.append(g)
    games.sort(key=lambda g: (g["date"] or "", g["id"]), reverse=True)
    print(f"{len(games)} games in {len(tours)} tournaments")

    if OUT.exists(): shutil.rmtree(OUT)
    for d in ("p", "t", "c", "g", "x"): (OUT / d).mkdir(parents=True)

    hist, team_games, champ_rows = defaultdict(list), defaultdict(list), defaultdict(list)
    pinfo, tinfo = {}, {}
    shards = defaultdict(dict)
    champ_t = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))  # champ -> tournament -> [picks, wins, bans]
    nx = 0
    for g in games:
        for p in g["players"]: p["ci"] = cid(p["c"], p["ck"])
        x = extras.get(str(g["id"]))
        g["x"] = 1 if x else 0
        if not x: continue
        nx += 1
        ck = {p["ck"]: p["ci"] for p in g["players"]}
        ev = [[e[0], e[1], e[2], e[3], ck.get(e[4], e[4]), [ck.get(a, a) for a in e[5]], ck.get(e[6], e[6]), e[7]] for e in x["ev"]]
        (OUT / "x" / f"{g['id']}.json").write_text(json.dumps(dict(gold=x["gold"], ev=ev, b=x["b"]), separators=(",", ":")), encoding="utf-8")
        for p in g["players"]:
            b = x["b"].get(str(p["pid"]))
            if not b: continue
            bo = b["bo"]
            p["ski"] = max_order(b["sk"]); p["sk"] = b["sk"][:18]; p["rn"] = b["rn"]
            p["stt"] = sorted(i for t, i in bo if t <= 90)
            core = []
            for t, i in bo:
                if i in big and i not in boots and i not in core: core.append(i)
            p["core"] = core[:3]
            p["bt"] = next((i for t, i in bo if i in boots), None)
    for g in games:
        for t in g["teams"]:
            t["bi"] = [cid(b) for b in t["bans"]]
            for b in t["bi"]: champ_t[b][g["t"]][2] += 1
        shards[g["t"]][g["id"]] = g
        mins = g["len"] / 60
        for side, t in enumerate(g["teams"]):
            opp = g["teams"][1 - side]
            mine = [p for p in g["players"] if p["side"] == side]
            if t["id"] not in tinfo:
                tinfo[t["id"]] = dict(id=t["id"], n=t["name"], rg=None, last=g["date"], **({"lo": logo[norm(t["name"])]} if norm(t["name"]) in logo else {}))
            team_games[t["id"]].append(dict(g=g["id"], t=g["t"], dt=g["date"], s=side, w=int(t["win"]), op=opp["id"], on=opp["name"], len=g["len"],
                k=t["k"], ok=opp["k"], pk=[p["ci"] for p in mine], opk=[p["ci"] for p in g["players"] if p["side"] != side], bn=t["bi"],
                ro=[[p["pid"], p["n"], p["role"]] for p in mine]))
        for p in g["players"]:
            st = p.get("st", {}); t = g["teams"][p["side"]]; opp = g["teams"][1 - p["side"]]
            lane = next((q for q in g["players"] if q["side"] != p["side"] and q["role"] == p["role"]), None)
            mates = [q for q in g["players"] if q["side"] == p["side"] and q is not p]
            row = dict(g=g["id"], t=g["t"], dt=g["date"], pa=g["patch"], c=p["ci"], r=p["role"], s=p["side"], w=int(t["win"]),
                k=p["k"], d=p["d"], a=p["a"], cs=p["cs"], len=g["len"], gold=st.get("gold"), dmg=st.get("dmg"), kp=st.get("kp"), vs=st.get("vs"),
                gd15=st.get("gd15"), csd15=st.get("csd15"), it=p["it"], ks=p["ks"], sub=p["sub"], sp=p["sp"], tm=t["id"], tn=t["name"],
                op=opp["id"], on=opp["name"], oc=lane["ci"] if lane else None, lvl=st.get("lvl"),
                opp=lane["pid"] if lane else None, mt=[q["pid"] for q in mates], x=g["x"])
            hist[p["pid"]].append(row)
            champ_t[p["ci"]][g["t"]][0] += 1; champ_t[p["ci"]][g["t"]][1] += int(t["win"])
            crow = dict(row, p=p["pid"], pn=p["n"], al=[q["ci"] for q in mates])
            del crow["mt"]
            for k in ("ski", "sk", "rn", "stt", "core", "bt"):
                if p.get(k) is not None: crow[k] = p[k]
            champ_rows[p["ci"]].append(crow)
            if p["pid"] not in pinfo:
                k = norm(p["n"])
                ph = (roster.get(norm(t["name"])) or {}).get(k) or anyp.get(k)
                pinfo[p["pid"]] = dict(id=p["pid"], n=p["n"], tm=t["id"], tn=t["name"], **({"ph": ph} if ph else {}))

    region_of = {t["s"]: t["lg"] for t in tours}
    players = []
    for pid, rows in hist.items():
        roles = Counter(r["r"] for r in rows); champs = Counter(r["c"] for r in rows)
        info = pinfo[pid]
        # tournament -> games, wins, kills, deaths, assists, cs, seconds, dmg, gd15 sum, gd15 n, kp sum, kp n, vision, gold
        by = defaultdict(lambda: [0] * 14)
        for r in rows:
            b = by[r["t"]]; b[0] += 1; b[1] += r["w"]; b[2] += r["k"] or 0; b[3] += r["d"] or 0; b[4] += r["a"] or 0; b[5] += r["cs"] or 0; b[6] += r["len"]
            b[7] += r["dmg"] or 0; b[10] += r["kp"] or 0; b[12] += r["vs"] or 0; b[13] += r["gold"] or 0
            if r["gd15"] is not None: b[8] += r["gd15"]; b[9] += 1
            if r["kp"] is not None: b[11] += 1
        for b in by.values(): b[10] = round(b[10], 1); b[12] = round(b[12], 1)
        players.append(dict(info, r=roles.most_common(1)[0][0], lg=Counter(region_of[r["t"]] for r in rows).most_common(1)[0][0],
            g=len(rows), by=dict(by), top=[c for c, _ in champs.most_common(3)]))
        (OUT / "p" / f"{pid}.json").write_text(json.dumps(dict(info, rows=rows), separators=(",", ":")), encoding="utf-8")
    teams = []
    for tid, rows in team_games.items():
        info = tinfo[tid]; info["lg"] = Counter(region_of[r["t"]] for r in rows).most_common(1)[0][0]
        by = defaultdict(lambda: [0, 0])
        for r in rows: by[r["t"]][0] += 1; by[r["t"]][1] += r["w"]
        teams.append(dict(info, g=len(rows), by=dict(by)))
        (OUT / "t" / f"{tid}.json").write_text(json.dumps(dict(info, rows=rows), separators=(",", ":")), encoding="utf-8")
    champions = []
    for c, per in champ_t.items():
        champions.append(dict(c=c, n=next((v[1] for v in dd["champs"].values() if v[0] == c), c), by={t: v for t, v in per.items()}))
        (OUT / "c" / f"{c}.json").write_text(json.dumps(dict(c=c, rows=champ_rows.get(c, [])), separators=(",", ":")), encoding="utf-8")
    # tier list: champion x tournament x patch x role picks/wins, bans, and game counts
    pidx = {pa: i for i, pa in enumerate(sorted({g["patch"] or "" for g in games}))}
    tidx = {t["s"]: i for i, t in enumerate(tours)}
    mp, mb, ng = defaultdict(lambda: [0, 0]), defaultdict(int), defaultdict(int)
    for g in games:
        ti, pi = tidx[g["t"]], pidx[g["patch"] or ""]
        ng[(ti, pi)] += 1
        for p in g["players"]:
            v = mp[(p["ci"], ti, pi, ROLES.index(p["role"]) if p["role"] in ROLES else 0)]; v[0] += 1; v[1] += int(g["teams"][p["side"]]["win"])
        for t in g["teams"]:
            for b in t["bi"]: mb[(b, ti, pi)] += 1
    (OUT / "meta.json").write_text(json.dumps(dict(tours=[t["s"] for t in tours], patches=list(pidx), roles=ROLES,
        p=[[*k, *v] for k, v in mp.items()], b=[[*k, v] for k, v in mb.items()], g=[[*k, v] for k, v in ng.items()]), separators=(",", ":")), encoding="utf-8")
    for t, gs in shards.items():
        (OUT / "g" / f"{t}.json").write_text(json.dumps(gs, separators=(",", ":")), encoding="utf-8")

    recent = [dict(g=g["id"], t=g["t"], dt=g["date"], len=g["len"], pa=g["patch"], st=g["stage"],
        tm=[[t["id"], t["name"], int(t["win"]), t["k"], [p["ci"] for p in g["players"] if p["side"] == i]] for i, t in enumerate(g["teams"])])
        for g in games[:400]]
    index = dict(built=games[0]["date"] if games else None, n=len(games), v=int(time.time()), dd=dict(ver=dd["ver"], items=dd["items"], big=dd["big"], runes=dd["runes"]),
        tours=sorted(tours, key=lambda t: t["b"] or "", reverse=True), players=sorted(players, key=lambda p: -p["g"]),
        teams=sorted(teams, key=lambda t: -t["g"]), champs=sorted(champions, key=lambda c: c["n"]), recent=recent,
        patches=sorted({g["patch"] for g in games if g["patch"]}, key=lambda v: [int(x) for x in v.split(".")], reverse=True))
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    shutil.copy(ROOT / "src" / "app.html", DIST / "index.html")
    if (ROOT / "static").exists(): shutil.copytree(ROOT / "static", DIST, dirs_exist_ok=True)
    unmatched = sorted(k for k, v in champ_id.items() if v not in {x[0] for x in dd["champs"].values()})
    if unmatched: print("champions not in Data Dragon:", unmatched, file=sys.stderr)
    size = sum(f.stat().st_size for f in OUT.rglob("*.json")) / 1e6
    print(f"{nx} games with extras; {sum('ph' in p for p in players)} player photos, {sum('lo' in t for t in teams)} team logos")
    print(f"{len(players)} players, {len(teams)} teams, {len(champions)} champions, {size:.1f} MB of data")

if __name__ == "__main__":
    main()
