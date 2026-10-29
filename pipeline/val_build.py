"""dist/val: the Valorant section (VCT 2026) built from data/val (see val.py).

  data/val/m/<tournament>.json   matches (series with maps, round halves, both comps)
  data/val/s/<tournament>.json   per-player tournament stat lines
  data/val/riot.json             team logos + VOD ids from Riot's esports API
  data/val/const.json            agent / map art from valorant-api.com

writes dist/val/data/{index,meta}.json, t/<team>.json, p/<player>.json, e/<tournament>.json, s/<series>.json,
the SPA shell (src/val.html), a static page per player / team / agent / map / tournament and val/sitemap.xml.
"""
import hashlib, html, json, re, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "val"
e = lambda s: html.escape(str(s or ""), quote=True)
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower().replace("esports", "").replace("gaming", "").replace("team", ""))
day = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")

def dump(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

def tour_name(title, info):
    rest = title.split("/", 2)[2]
    if rest == "Champions": return "Champions 2026", "Champions"
    m = re.match(r"Stage (\d)/Masters", rest)
    if m:
        city = (info.get("Location") or "").split(",")[0].strip()
        return (f"Masters {city} 2026" if city else f"Masters 2026 · Stage {m[1]}"), "Masters"
    lg, stage = rest.split("/", 1)
    lg = lg.replace(" League", "")
    return f"VCT {lg} {stage}", lg

def build(dist, site, ads=""):
    files = sorted((D / "m").glob("*.json")) if (D / "m").exists() else []
    if not files: print("val: no data yet"); return
    const = json.loads((D / "const.json").read_text(encoding="utf-8")) if (D / "const.json").exists() else {"agents": {}, "maps": {}}
    riot = json.loads((D / "riot.json").read_text(encoding="utf-8")) if (D / "riot.json").exists() else {"teams": {}, "matches": {}, "leagues": {}}
    rlogo = {norm(k): v for k, v in riot["teams"].items()}
    rvod = defaultdict(list)
    for m in riot["matches"].values():
        if m.get("v"): rvod[m["d"]].append(m)
    out = dist / "val" / "data"

    tours, series, prows = [], [], defaultdict(list)
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        ms = [m for m in d["matches"] if m["maps"]]
        if not ms: continue
        tid = f.stem.replace("vct-2026-", "")
        name, lg = tour_name(d["title"], d.get("info") or {})
        info = d.get("info") or {}
        tours.append(dict(id=tid, n=name, lg=lg, a=day(ms[0]["ts"]), b=day(ms[-1]["ts"]), g=len(ms), maps=sum(len(m["maps"]) for m in ms),
                          loc=info.get("Location") or "", prize=info.get("Prize Pool") or "", lp=d["title"]))
        for i, m in enumerate(ms):
            sid = f"{tid}-{i + 1}"
            dt = day(m["ts"])
            vods = []  # Riot VODs: same day (±1), both team names match
            for dd in {dt, day(m["ts"] - 86400), day(m["ts"] + 86400)}:
                for r in rvod.get(dd, []):
                    names = [norm(x) for x in r["t"]]
                    if all(any(norm(t) == n or (len(n) > 2 and (n in norm(t) or norm(t) in n)) for n in names) for t in m["t"]): vods = r["v"]
            series.append(dict(id=sid, e=tid, ts=m["ts"], dt=dt, t=m["t"], s=m["s"], bo=m["bo"], w=m["w"] if m["w"] is not None else (0 if m["s"] and m["s"][0] > m["s"][1] else 1),
                               maps=[dict(x, v=(vods[j] if j < len(vods) else "")) for j, x in enumerate(m["maps"])]))
        seen = set()  # Statistics pages repeat the table per stage; the first one is the whole event
        for r in json.loads((D / "s" / f.name).read_text(encoding="utf-8")) if (D / "s" / f.name).exists() else []:
            if slug(r["id"]) in seen: continue
            seen.add(slug(r["id"])); prows[slug(r["id"])].append(dict(r, e=tid))
    tours.sort(key=lambda t: t["b"], reverse=True)
    tinfo = {t["id"]: t for t in tours}
    series.sort(key=lambda s: -s["ts"])

    # teams: series + map records, map pool, attack/defence rounds, comps
    teams = {}
    def team(n):
        k = slug(n)
        if k not in teams:
            lo = rlogo.get(norm(n))
            if not lo: lo = next((v for kk, v in rlogo.items() if len(kk) > 3 and (kk in norm(n) or norm(n) in kk)), None)
            teams[k] = dict(id=k, n=n, tag=(lo or [None])[0], lo=(lo or [None, None])[1], sw=0, sl=0, mw=0, ml=0, rw=0, rl=0, atk=[0, 0], dfn=[0, 0],
                            pool=defaultdict(lambda: [0, 0]), lgs=Counter(), last="", rows=[])
        return teams[k]
    agent_map = defaultdict(lambda: [0, 0])          # (agent, map) -> [picks, wins]
    map_st = defaultdict(lambda: dict(g=0, atk=0, dfn=0, ot=0))
    comps = defaultdict(lambda: [0, 0])              # (map, comp) -> [picks, wins]
    for s in series:
        A, B = team(s["t"][0]), team(s["t"][1])
        for side, (me, op) in enumerate(((A, B), (B, A))):
            won = s["w"] == side
            me["sw" if won else "sl"] += 1; me["lgs"][tinfo[s["e"]]["lg"]] += 1; me["last"] = max(me["last"], s["dt"])
            me["rows"].append(dict(id=s["id"], e=s["e"], dt=s["dt"], op=op["id"], on=op["n"], w=int(won), s=[s["s"][side], s["s"][1 - side]] if s["s"] else None,
                                   maps=[[x["map"], x["s"][side], x["s"][1 - side], x["ag"][side] if side < len(x["ag"]) else []] for x in s["maps"]]))
            for x in s["maps"]:
                mw = x["s"][side] > x["s"][1 - side]
                me["mw" if mw else "ml"] += 1; me["rw"] += x["s"][side]; me["rl"] += x["s"][1 - side]
                me["pool"][x["map"]][0] += 1; me["pool"][x["map"]][1] += mw
                for sd, r in (x["h"][side] if side < len(x["h"]) else [])[:2]:
                    (me["atk"] if sd == "a" else me["dfn"])[0] += r
                for sd, r in (x["h"][1 - side] if 1 - side < len(x["h"]) else [])[:2]:  # rounds the opponent won on a side = we lost on the other
                    (me["dfn"] if sd == "a" else me["atk"])[1] += r
                ag = x["ag"][side] if side < len(x["ag"]) else []
                for a in ag: agent_map[(a, x["map"])][0] += 1; agent_map[(a, x["map"])][1] += mw
                if len(ag) == 5: c = comps[(x["map"], ",".join(sorted(ag)))]; c[0] += 1; c[1] += mw
        for x in s["maps"]:
            st = map_st[x["map"]]; st["g"] += 1
            if max(x["s"]) > 13: st["ot"] += 1
            for h in x["h"]:
                for sd, r in h[:2]: st["atk" if sd == "a" else "dfn"] += r

    # players: tournament lines -> career (map-weighted)
    roles = {a: v.get("role") for a, v in const["agents"].items()}
    players = []
    for pid, rows in prows.items():
        rows.sort(key=lambda r: tinfo.get(r["e"], {}).get("b", ""), reverse=True)
        m = sum(r["m"] for r in rows)
        if not m: continue
        w = lambda k: sum(r[k] * r["m"] for r in rows) / m
        ag = Counter()
        for r in rows:
            for i, a in enumerate(r["ag"]): ag[a] += r["m"] / (i + 1)
        rl = Counter()
        for a, n in ag.items(): rl[roles.get(a) or "Flex"] += n
        tm = team(rows[0]["tm"]) if rows[0]["tm"] else None
        K, Dd, A, FK, FD = (sum(r[k] for r in rows) for k in ("k", "d", "a", "fk", "fd"))
        players.append(dict(id=pid, n=rows[0]["n"], cc=rows[0]["cc"], tm=tm["id"] if tm else "", tn=rows[0]["tm"], role=rl.most_common(1)[0][0] if rl else "Flex",
                            ag=[a for a, _ in ag.most_common(4)], lg=next((tinfo[r["e"]]["lg"] for r in rows if tinfo.get(r["e"], {}).get("lg") not in (None, "Champions", "Masters")), ""),
                            s=[m, round(w("acs"), 1), round(w("adr"), 1), K, Dd, A, FK, FD, round(w("kast"), 1)],
                            by={r["e"]: [r["m"], r["acs"], r["adr"], r["k"], r["d"], r["a"], r["fk"], r["fd"], r["kast"]] for r in rows}))
        dump(out / "p" / f"{pid}.json", dict(rows=[dict(r, tn=r["tm"]) for r in rows]))
    # roster = who played for the team at its latest event (stand-ins and old lineups drop off)
    latest = {}
    for pid, rows in prows.items():
        for r in rows:
            k = slug(r["tm"]); b = tinfo.get(r["e"], {}).get("b", "")
            if b > latest.get(k, ("", None))[0]: latest[k] = (b, r["e"])
    roster = defaultdict(list)
    for pid, rows in prows.items():
        for r in rows:
            if latest.get(slug(r["tm"]), ("", None))[1] == r["e"]: roster[slug(r["tm"])].append((r["m"], pid))
    roster = {k: [pid for _, pid in sorted(v, reverse=True)[:5]] for k, v in roster.items()}

    tl = []
    for t in teams.values():
        g = t["sw"] + t["sl"]
        dump(out / "t" / f"{t['id']}.json", dict(rows=t["rows"], pool={k: v for k, v in sorted(t["pool"].items(), key=lambda kv: -kv[1][0])}))
        tl.append(dict(id=t["id"], n=t["n"], tag=t["tag"], lo=t["lo"], g=g, sw=t["sw"], mw=t["mw"], ml=t["ml"], rw=t["rw"], rl=t["rl"], atk=t["atk"], dfn=t["dfn"],
                       lg=t["lgs"].most_common(1)[0][0] if t["lgs"] else "", last=t["last"], ro=roster.get(t["id"], [])))
    for s in series: dump(out / "s" / f"{s['id']}.json", s)
    for t in tours:
        dump(out / "e" / f"{t['id']}.json", dict(series=[s for s in series if s["e"] == t["id"]],
                                                 stats=sorted(([p["id"], *p["by"][t["id"]]] for p in players if t["id"] in p["by"]), key=lambda r: -r[2])))
    meta = dict(am=[[a, mp, *v] for (a, mp), v in agent_map.items()], maps={k: v for k, v in map_st.items()},
                comps=sorted(([mp, c, *v] for (mp, c), v in comps.items() if v[0] >= 2), key=lambda r: -r[2])[:300])
    dump(out / "meta.json", meta)
    total_tm = sum(len(s["maps"]) for s in series) * 2
    # season records (front page)
    allmaps = [(s, x) for s in series for x in s["maps"]]
    rec = {}
    if allmaps:
        lng = max(allmaps, key=lambda sx: sum(sx[1]["s"]))
        stomp = [sx for sx in allmaps if min(sx[1]["s"]) == 0]
        best = max((r for p in players for r in prows[p["id"]] if r["m"] >= 6), key=lambda r: r["acs"], default=None)
        rec = dict(long=[lng[0]["id"], lng[1]["map"], lng[1]["s"], lng[0]["t"]], stomps=len(stomp),
                   stomp=[stomp[0][0]["id"], stomp[0][1]["map"], stomp[0][1]["s"], stomp[0][0]["t"]] if stomp else None,
                   acs=[slug(best["id"]), best["n"], best["acs"], best["e"], best["m"]] if best else None,
                   ot=sum(1 for _, x in allmaps if max(x["s"]) > 13))
    index = dict(v=int(time.time()), n=len(series), nm=total_tm // 2, tours=tours, teams=sorted(tl, key=lambda t: -t["g"]),
                 players=sorted(players, key=lambda p: -p["s"][0]), agents=const["agents"], mapart=const["maps"], rec=rec,
                 leagues=riot.get("leagues", {}),
                 recent=[dict(id=s["id"], e=s["e"], dt=s["dt"], t=s["t"], s=s["s"], w=s["w"], maps=[[x["map"], x["s"]] for x in s["maps"]]) for s in series[:30]])
    dump(out / "index.json", index)
    write_pages(dist, site, index, ads)
    print(f"val: {len(tours)} tournaments, {len(series)} series, {total_tm // 2} maps, {len(players)} players, {len(tl)} teams")

def write_pages(dist, site, idx, ads=""):
    src = (ROOT / "src" / "val.html").read_text(encoding="utf-8")
    base = re.sub(r"^https?://[^/]+", "", site) or "/"
    js_a, js_b = src.index("<script>"), src.index("</script>")
    css_a, css_b = src.index("<style>"), src.index("</style>")
    js, css = src[js_a + 8:js_b], src[css_a + 7:css_b]
    v = hashlib.md5((js + css).encode()).hexdigest()[:10]
    lol_css = (dist / "app.css").read_text(encoding="utf-8")
    (dist / "val" / "val.js").write_text(js, encoding="utf-8")
    (dist / "val" / "val.css").write_text(lol_css + "\n" + css, encoding="utf-8")
    shell = (src[:css_a] + f'<link rel="stylesheet" href="val.css?v={v}">' + src[css_b + 8:js_a] + f'<script src="val.js?v={v}"></script>' + src[js_b + 9:])
    shell = shell.replace("https://techreign.github.io/rift-ledger/", site)
    shell = shell.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n<base href="{base}val/">', 1)
    tags = re.findall(r'<meta name="(?:google-adsense-account|ad-slot)"[^>]*>|<script async src="https://pagead2[^>]*></script>', ads)
    shell = shell.replace("</head>", "".join(tags) + "\n</head>", 1)
    APP = re.compile(r'(<div class="wrap" id="app">).*?(</div></main>)', re.S)
    urls = []

    def render(path, title, desc, body):
        h = re.sub(r"<title>.*?</title>", lambda m: f"<title>{e(title)}</title>", shell, count=1)
        for pat, val in ((r'(<meta name="description" content=")[^"]*', desc), (r'(<meta property="og:title" content=")[^"]*', title),
                         (r'(<meta property="og:description" content=")[^"]*', desc), (r'(<link rel="canonical" href=")[^"]*', site + "val/" + path),
                         (r'(<meta property="og:url" content=")[^"]*', site + "val/" + path)):
            h = re.sub(pat, lambda m: m[1] + e(val), h, count=1)
        h = APP.sub(lambda m: m[1] + f'<div class="card seo">{body}</div>' + m[2], h, count=1)
        o = dist / "val" / path / "index.html" if path else dist / "val" / "index.html"
        o.parent.mkdir(parents=True, exist_ok=True); o.write_text(h, encoding="utf-8")
        urls.append("val/" + path)

    for p in idx["players"]:
        m, acs, adr, k, d, a = p["s"][:6]
        render(f"player/{p['id']}/", f"{p['n']} ({p['tn']}) – VALORANT Pro Stats & Agents | prostats.gg",
               f"{p['n']}, {p['role']} for {p['tn']}: {m} VCT 2026 maps, {acs:.0f} ACS, {k / max(d, 1):.2f} K/D, {adr:.0f} ADR. Agents, tournaments and every series.",
               f"<h1>{e(p['n'])}</h1><p>{e(p['role'])} · {e(p['tn'])}</p><p>{m} maps · {acs:.0f} ACS · {k}/{d}/{a}</p>")
    for t in idx["teams"]:
        render(f"team/{t['id']}/", f"{t['n']} – VALORANT Team Stats, Map Pool & Results | prostats.gg",
               f"{t['n']} in VCT 2026: {t['sw']}–{t['g'] - t['sw']} in series, {t['mw']}–{t['ml']} on maps. Map pool, comps, roster and every series.",
               f"<h1>{e(t['n'])}</h1><p>{t['sw']}W {t['g'] - t['sw']}L series · {t['mw']}–{t['ml']} maps</p>")
    for a in idx["agents"]:
        render(f"agent/{slug(a)}/", f"{a} – VALORANT Pro Pick Rate, Win Rate & Best Players | prostats.gg",
               f"{a} in VCT 2026: pick and win rate on every map, the comps it's in and the pros who play it best.", f"<h1>{e(a)}</h1>")
    for mp in idx["mapart"]:
        render(f"map/{slug(mp)}/", f"{mp} – VALORANT Pro Map Stats, Comps & Attack/Defence | prostats.gg",
               f"{mp} in VCT 2026: attack vs defence round win rates, most picked agents and comps, and every pro map played.", f"<h1>{e(mp)}</h1>")
    for t in idx["tours"]:
        render(f"event/{t['id']}/", f"{t['n']} – Results, Bracket & Player Stats | prostats.gg",
               f"{t['n']} ({t['a']} to {t['b']}): every series and map, standings, comps and player stats.", f"<h1>{e(t['n'])}</h1><p>{t['g']} series · {t['maps']} maps</p>")
    for path, t in (("agents/", "VALORANT Pro Agent Tier List"), ("maps/", "VALORANT Pro Map Stats"), ("players/", "VALORANT Pro Player Rankings"),
                    ("teams/", "VALORANT Pro Teams"), ("events/", "VCT 2026 Tournaments")):
        render(path, f"{t} | prostats.gg", f"{t} from every VCT 2026 match.", f"<h1>{e(t)}</h1>")
    render("", "prostats.gg – VALORANT Pro Stats, VCT Results & Agent Tier List",
           "op.gg for pro VALORANT: every VCT 2026 series and map, player stats, team map pools, comps and a pro agent tier list.",
           "<h1>VALORANT pro stats</h1>" + "".join(f'<a href="player/{p["id"]}/">{e(p["n"])}</a> ' for p in idx["players"][:80]))
    sm = "".join(f"<url><loc>{e(site + u)}</loc></url>" for u in urls)
    (dist / "val" / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>\n', encoding="utf-8")
