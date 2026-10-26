"""Build the static site: dist/index.html + dist/data/*.json from data/games/*.json.

Outputs (all fetched lazily by the app):
  data/index.json         tournaments, players, teams, champions (with per-tournament counts), recent games, Data Dragon refs
  data/p/<pid>.json       a player's match history
  data/t/<tid>.json       a team's games
  data/c/<champ>.json     every pro pick of a champion
  data/g/<tournament>.json  full game details (scoreboard + all stats), keyed by game id
  data/x/<game>.json      per-game extras (gold per minute, event log, build/skill order, full runes) when scraped
  data/meta.json          champion picks/wins by tournament x patch x role (+ bans) for the tier list
  data/h/...              earlier seasons from Oracle's Elixir (data/oe, made by oracle.py): index.json, meta.json, p/ t/ c/
                          (their g/ shards sit with the rest); only fetched when a viewer picks a past season
"""
import gzip, json, re, shutil, sys, time, unicodedata, urllib.request
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
def norm(s):  # accents folded so 'LEVIATÁN' == 'Leviatan'
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
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
            if not p.exists(): return (lambda name: None), {}
    teams = json.loads(p.read_text(encoding="utf-8"))["data"]["teams"]
    teams.sort(key=lambda t: t.get("status") != "active")  # active teams win name clashes
    https = lambda u: (u or "").replace("http://", "https://")
    exact, anyp = {}, defaultdict(list)
    entries = []  # (loose name, active?, entry) for the contains-match fallback
    for t in teams:
        if not t.get("image"): continue
        e = dict(logo=https(t["image"]), roster={})
        for pl in t.get("players") or []:
            img = https(pl.get("image"))
            if not img or "default-headshot" in img: continue
            e["roster"].setdefault(norm(pl["summonerName"]), img)
            anyp[(norm(pl["summonerName"]), LOLROLE.get(pl.get("role"), pl.get("role")))].append(img)
        for k in (norm(t["name"]), loose(t["name"])):
            if k: exact.setdefault(k, e)
        entries.append((loose(t["name"]), t.get("status") == "active", e))

    def team(name):
        name = TEAM_ALIAS.get(name, name)
        """gol.gg team name -> lolesports entry: exact, then sponsor-stripped, then the shortest active lolesports
        name that contains it ('Cloud9' -> 'Cloud9 Kia', 'Team Liquid' -> 'Team Liquid Alienware')."""
        hit = exact.get(norm(name)) or exact.get(loose(name))
        if hit: return hit
        k = loose(name)
        if len(k) < 4: return None  # 'JD', 'WE' would match half the list
        cands = sorted((len(n), i) for i, (n, active, e) in enumerate(entries) if active and k in n)
        return entries[cands[0][1]][2] if cands else None
    # outside a team match, only trust a name+role that points at exactly one photo
    return team, {k: v[0] for k, v in anyp.items() if len(set(v)) == 1}

# gol.gg name -> lolesports name where they share no usable words (city prefixes, academy brands)
TEAM_ALIAS = {"JD Gaming": "Beijing JDG Esports", "Team WE": "Xi'an Team WE", "LNG Esports": "Suzhou LNG Esports",
    "Nongshim Esports Academy": "NONGSHIM RED FORCE", "KT Rolster Challengers": "kt Challengers", "DN SOOPers Challengers": "DN SOOPers",
    "Dplus KIA Challengers": "DK Challengers", "Hanwha Life Esports Challengers": "HLE Challengers", "HANJIN BRION Challengers": "BRO Challengers",
    "Los Grandes": "Fla Los Grandes", "3BL Esports": "3BL GALAXY ESPORTS"}
LOLROLE = {"bottom": "adc", "top": "top", "jungle": "jungle", "mid": "mid", "support": "support"}
def loose(name):
    """'Hanwha Life Esports' / 'Xi'an Team WE' -> core name, for matching when sponsor words differ"""
    return norm(re.sub(r"\b(e-?sports?|gaming|team|club|the)\b", " ", (name or "").lower()))

def recent_games(games, tours, n=400, per=20, per_t=14):
    """newest n overall plus the newest `per` of every league/tournament, so a home-page filter is never empty"""
    lg = {t["s"]: t["lg"] for t in tours}
    keep, seen_t, seen_l = [], defaultdict(int), defaultdict(int)
    for i, g in enumerate(games):  # games are newest first
        if i < n or seen_t[g["t"]] < per_t or seen_l[lg[g["t"]]] < per: keep.append(g)
        seen_t[g["t"]] += 1; seen_l[lg[g["t"]]] += 1
    return keep

def gz(path, obj):
    """past seasons are big and repetitive: stored gzipped (Pages has a 1 GB cap), the app inflates them with DecompressionStream"""
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as f: json.dump(obj, f, separators=(",", ":"))

def player_by(rows):
    """tournament -> games, wins, kills, deaths, assists, cs, seconds, dmg, gd15 sum, gd15 n, kp sum, kp n, vision, gold"""
    by = defaultdict(lambda: [0] * 14)
    for r in rows:
        b = by[r["t"]]; b[0] += 1; b[1] += r["w"]; b[2] += r.get("k") or 0; b[3] += r.get("d") or 0; b[4] += r.get("a") or 0; b[5] += r.get("cs") or 0; b[6] += r["len"]
        b[7] += r.get("dmg") or 0; b[10] += r.get("kp") or 0; b[12] += r.get("vs") or 0; b[13] += r.get("gold") or 0
        if r.get("gd15") is not None: b[8] += r["gd15"]; b[9] += 1
        if r.get("kp") is not None: b[11] += 1
    for b in by.values(): b[10] = round(b[10], 1); b[12] = round(b[12], 1)
    return dict(by)

def write_meta(path, games, tours):
    """tier list: champion x tournament x patch x role picks/wins, bans, and game counts"""
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
    meta = dict(tours=[t["s"] for t in tours], patches=list(pidx), roles=ROLES,
        p=[[*k, *v] for k, v in mp.items()], b=[[*k, v] for k, v in mb.items()], g=[[*k, v] for k, v in ng.items()])
    if path.suffix == ".gz": gz(path, meta)
    else: path.write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")

def lifetime(cid, cname, team_of, anyp, gol_players, gol_teams):
    """Earlier seasons from Oracle's Elixir -> dist/data/h/* and g/<tournament>.json. Oracle ids are linked to 2026
    gol.gg ids through data/oe/bridge.json (Oracle's own 2026 rows), so a current pro's page carries their whole
    career; everyone else gets an 'o'-prefixed id. Returns ({2026 player id: {year: [games, wins]}}, seasons)."""
    src = ROOT / "data" / "oe"
    files = sorted(src.glob("*.json.gz")) if src.exists() else []
    if not files: return {}, []
    tours, games = [], []
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh: doc = json.load(fh)
        tours += doc["tours"]; games += doc["games"]
    games.sort(key=lambda g: (g["date"], g["id"]), reverse=True)
    br = json.loads((src / "bridge.json").read_text(encoding="utf-8")) if (src / "bridge.json").exists() else dict(players=[], teams=[])
    by_nt, by_nr = {}, defaultdict(list)
    for p in gol_players:
        by_nt[(norm(p["n"]), loose(p["tn"]))] = p["id"]; by_nr[(norm(p["n"]), p["r"])].append(p["id"])
    pmap = {}
    for o, n, tn, r in br["players"]:
        hit = by_nt.get((norm(n), loose(tn))) or (by_nr[(norm(n), r)][0] if len(by_nr[(norm(n), r)]) == 1 else None)
        if hit: pmap.setdefault(o, hit)
    # players missing from Oracle's 2026 file: same name + role as exactly one 2026 pro, and still playing in 2025
    last = {}
    for g in games:
        for p in g["players"]:
            if p["oid"] not in last: last[p["oid"]] = (g["date"], p["n"], p["role"])
    taken = set(pmap.values())
    for o, (dt, n, r) in last.items():
        c = by_nr.get((norm(n), r), [])
        if o not in pmap and dt >= "2025-01-01" and len(c) == 1 and c[0] not in taken: pmap[o] = c[0]; taken.add(c[0])
    tnames = {}
    for t in gol_teams:
        for k in (norm(t["n"]), loose(t["n"])):
            if k: tnames.setdefault(k, t["id"])
    tmap = {o: tnames.get(norm(n)) or tnames.get(loose(n)) for o, n in br["teams"]}
    pid = lambda o: pmap.get(o) or "o" + o
    tid = lambda o: tmap.get(o) or "o" + o

    for d in ("p", "t", "c"): (OUT / "h" / d).mkdir(parents=True, exist_ok=True)
    hist, team_games, champ_rows, shards = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(dict)
    champ_t = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    pinfo, tinfo = {}, {}
    clean = lambda d: {k: v for k, v in d.items() if v is not None}
    for g in games:
        t = g["t"]
        for tm in g["teams"]:
            tm["id"] = tid(tm.pop("oid")); tm["bi"] = [cid(b) for b in tm.pop("bans")]; tm["obj"] = []
            for b in tm["bi"]: champ_t[b][t][2] += 1
            if tm["id"] not in tinfo:
                tinfo[tm["id"]] = dict(id=tm["id"], n=tm["name"], **({"lo": e["logo"]} if (e := team_of(tm["name"])) else {}))
        for p in g["players"]:
            p["pid"] = pid(p.pop("oid")); p.pop("tm"); p["ci"] = cid(p.pop("c")); p["it"] = []
        shards[t][g["id"]] = g
        for side, tm in enumerate(g["teams"]):
            opp = g["teams"][1 - side]; mine = [p for p in g["players"] if p["side"] == side]
            team_games[tm["id"]].append(dict(g=g["id"], t=t, dt=g["date"], s=side, w=int(tm["win"]), op=opp["id"], on=opp["name"], len=g["len"],
                k=tm["k"], ok=opp["k"], pk=[p["ci"] for p in mine], opk=[p["ci"] for p in g["players"] if p["side"] != side], bn=tm["bi"],
                ro=[[p["pid"], p["n"], p["role"]] for p in mine]))
        for p in g["players"]:
            st, tm, opp = p["st"], g["teams"][p["side"]], g["teams"][1 - p["side"]]
            lane = next((q for q in g["players"] if q["side"] != p["side"] and q["role"] == p["role"]), None)
            mates = [q for q in g["players"] if q["side"] == p["side"] and q is not p]
            row = clean(dict(g=g["id"], t=t, dt=g["date"], pa=g["patch"], c=p["ci"], r=p["role"], s=p["side"], w=int(tm["win"]),
                k=p["k"], d=p["d"], a=p["a"], cs=p["cs"], len=g["len"], gold=st.get("gold"), dmg=st.get("dmg"), kp=st.get("kp"), vs=st.get("vs"),
                gd15=st.get("gd15"), csd15=st.get("csd15"), tm=tm["id"], tn=tm["name"], op=opp["id"], on=opp["name"],
                oc=lane["ci"] if lane else None, opp=lane["pid"] if lane else None))
            hist[p["pid"]].append(dict(row, mt=[q["pid"] for q in mates]))
            champ_rows[p["ci"]].append(dict(row, p=p["pid"], pn=p["n"], al=[q["ci"] for q in mates]))
            champ_t[p["ci"]][t][0] += 1; champ_t[p["ci"]][t][1] += int(tm["win"])
            if p["pid"] not in pinfo:  # games are newest first: latest name and team
                k = norm(p["n"]); ph = ((team_of(tm["name"]) or {}).get("roster") or {}).get(k) or anyp.get((k, p["role"]))
                pinfo[p["pid"]] = dict(id=p["pid"], n=p["n"], tm=tm["id"], tn=tm["name"], **({"ph": ph} if ph else {}))
    year = {t["s"]: t["y"] for t in tours}
    league = {t["s"]: t["lg"] for t in tours}
    players, yrs = [], {}
    for p, rows in hist.items():
        info = pinfo[p]
        players.append(dict(info, r=Counter(r["r"] for r in rows).most_common(1)[0][0], lg=Counter(league[r["t"]] for r in rows).most_common(1)[0][0],
            g=len(rows), by=player_by(rows), top=[c for c, _ in Counter(r["c"] for r in rows).most_common(3)]))
        gz(OUT / "h" / "p" / f"{p}.json.gz", dict(info, rows=rows))
        if not str(p).startswith("o"):
            y = defaultdict(lambda: [0, 0])
            for r in rows: y[year[r["t"]]][0] += 1; y[year[r["t"]]][1] += r["w"]
            yrs[p] = dict(y)
    teams = []
    for t, rows in team_games.items():
        info = tinfo[t]; by = defaultdict(lambda: [0, 0])
        for r in rows: by[r["t"]][0] += 1; by[r["t"]][1] += r["w"]
        teams.append(dict(info, lg=Counter(league[r["t"]] for r in rows).most_common(1)[0][0], g=len(rows), by=dict(by)))
        gz(OUT / "h" / "t" / f"{t}.json.gz", dict(info, rows=rows))
    for c, rows in champ_rows.items():
        gz(OUT / "h" / "c" / f"{c}.json.gz", dict(c=c, rows=rows))
    for t, gs in shards.items():
        gz(OUT / "g" / f"{t}.json.gz", gs)
    write_meta(OUT / "h" / "meta.json.gz", games, tours)
    for t in tours:
        ds = [g["date"] for g in shards[t["s"]].values()]
        t.update(g=len(ds), a=min(ds), b=max(ds))
    recent = []
    for y in sorted({t["y"] for t in tours}, reverse=True):
        recent += recent_games([g for g in games if year[g["t"]] == y], [t for t in tours if t["y"] == y], n=60, per=6, per_t=3)
    recent = [dict(g=g["id"], t=g["t"], dt=g["date"], len=g["len"], pa=g["patch"],
        tm=[[t["id"], t["name"], int(t["win"]), t["k"], [p["ci"] for p in g["players"] if p["side"] == i]] for i, t in enumerate(g["teams"])]) for g in recent]
    seasons = [dict(y=y, n=sum(t["g"] for t in tours if t["y"] == y)) for y in sorted({t["y"] for t in tours}, reverse=True)]
    gz(OUT / "h" / "index.json.gz", dict(n=len(games), tours=sorted(tours, key=lambda t: t["b"], reverse=True),
        players=sorted(players, key=lambda p: -p["g"]), teams=sorted(teams, key=lambda t: -t["g"]),
        champs=[dict(c=c, n=cname.get(c, c), by=dict(per)) for c, per in champ_t.items()], recent=recent))
    linked = sum(1 for p in pinfo if not str(p).startswith("o"))
    print(f"lifetime: {len(games)} games {seasons[-1]['y']}-{seasons[0]['y']}, {len(players)} players ({linked} linked to 2026 pros), {len(teams)} teams")
    return yrs, seasons

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

    team_of, anyp = lolesports()
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
                tinfo[t["id"]] = dict(id=t["id"], n=t["name"], rg=None, last=g["date"], **({"lo": e["logo"]} if (e := team_of(t["name"])) else {}))
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
                ph = ((team_of(t["name"]) or {}).get("roster") or {}).get(k) or anyp.get((k, p["role"]))
                pinfo[p["pid"]] = dict(id=p["pid"], n=p["n"], tm=t["id"], tn=t["name"], **({"ph": ph} if ph else {}))

    region_of = {t["s"]: t["lg"] for t in tours}
    players = []
    for pid, rows in hist.items():
        roles = Counter(r["r"] for r in rows); champs = Counter(r["c"] for r in rows)
        info = pinfo[pid]
        players.append(dict(info, r=roles.most_common(1)[0][0], lg=Counter(region_of[r["t"]] for r in rows).most_common(1)[0][0],
            g=len(rows), by=player_by(rows), top=[c for c, _ in champs.most_common(3)]))
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
    write_meta(OUT / "meta.json", games, tours)
    for t, gs in shards.items():
        (OUT / "g" / f"{t}.json").write_text(json.dumps(gs, separators=(",", ":")), encoding="utf-8")

    recent = [dict(g=g["id"], t=g["t"], dt=g["date"], len=g["len"], pa=g["patch"], st=g["stage"],
        tm=[[t["id"], t["name"], int(t["win"]), t["k"], [p["ci"] for p in g["players"] if p["side"] == i]] for i, t in enumerate(g["teams"])])
        for g in recent_games(games, tours)]
    for t in tours: t["y"] = 2026
    yrs, seasons = lifetime(cid, {v[0]: v[1] for v in dd["champs"].values()}, team_of, anyp, players, teams)
    for p in players:
        if p["id"] in yrs: p["yrs"] = yrs[p["id"]]
    index = dict(built=games[0]["date"] if games else None, n=len(games), v=int(time.time()), seasons=[dict(y=2026, n=len(games))] + seasons, dd=dict(ver=dd["ver"], items=dd["items"], big=dd["big"], runes=dd["runes"]),
        tours=sorted(tours, key=lambda t: t["b"] or "", reverse=True), players=sorted(players, key=lambda p: -p["g"]),
        teams=sorted(teams, key=lambda t: -t["g"]), champs=sorted(champions, key=lambda c: c["n"]), recent=recent,
        patches=sorted({g["patch"] for g in games if g["patch"]}, key=lambda v: [int(x) for x in v.split(".")], reverse=True))
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    shutil.copy(ROOT / "src" / "app.html", DIST / "index.html")
    if (ROOT / "static").exists(): shutil.copytree(ROOT / "static", DIST, dirs_exist_ok=True)
    unmatched = sorted(k for k, v in champ_id.items() if v not in {x[0] for x in dd["champs"].values()})
    if unmatched: print("champions not in Data Dragon:", unmatched, file=sys.stderr)
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"{nx} games with extras; {sum('ph' in p for p in players)} player photos, {sum('lo' in t for t in teams)} team logos")
    print(f"{len(players)} players, {len(teams)} teams, {len(champions)} champions, {size:.1f} MB of data")

if __name__ == "__main__":
    main()
