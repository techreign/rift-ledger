"""dist/cs: the Counter-Strike 2 section (2026 S-Tier) built from data/cs (see cs.py).

  data/cs/tours.json        the 2026 S-Tier events (dates, prize, location, winner)
  data/cs/m/<event>.json    matches (series with maps, round halves by side, VODs), rosters, placements
  data/cs/vrs.json          Valve's latest global VRS ranking

writes dist/cs/data/{index,meta}.json, t/<team>.json, p/<player>.json, e/<event>.json, s/<series>.json,
the SPA shell (src/cs.html), a static page per player / team / map / event and cs/sitemap.xml.
"""
import json, re, time
from collections import Counter, defaultdict
from pathlib import Path
import val_build
from val_build import dump, e, slug, day

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "cs"
norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())

def short(name):
    for a, b in (("Intel Extreme Masters", "IEM"), ("ESL Pro League", "EPL"), ("StarLadder StarSeries", "StarSeries"), ("Esports World Cup", "EWC"),
                 ("Thunderpick World Championship", "Thunderpick Worlds")):
        name = name.replace(a, b)
    return name

def series_of(name):
    for k in ("Major", "IEM", "BLAST", "PGL", "EPL", "StarSeries", "EWC", "FISSURE", "Thunderpick", "CS Asia"):
        if k in name: return k
    return "Other"

def build(dist, site, ads=""):
    files = {f.stem: f for f in (D / "m").glob("*.json")} if (D / "m").exists() else {}
    if not files: print("cs: no data yet"); return
    tl = json.loads((D / "tours.json").read_text(encoding="utf-8"))
    vrs = json.loads((D / "vrs.json").read_text(encoding="utf-8")) if (D / "vrs.json").exists() else {"date": "", "rows": []}
    out = dist / "cs" / "data"

    tours, series, upcoming = [], [], []
    rosters = {}                                   # event id -> team -> [player ids]
    pinfo = {}                                     # player id -> [name, country]
    for t in tl:
        f = files.get(val_build.slug(t["page"]))
        d = json.loads(f.read_text(encoding="utf-8")) if f else {}
        ms = [m for m in d.get("matches", []) if m["maps"]]
        name = short(t["name"])
        eid = slug(name)
        info = d.get("info") or {}
        row = dict(id=eid, n=name, s=series_of(name), a=info.get("Start Date") or "", b=info.get("End Date") or "", dates=t["dates"], prize=t["prize"],
                   loc=t["loc"], nt=t["n"], win=t["win"], second=t["second"], lp=t["page"], major="Major" in t["name"] or "Major" in (info.get("Series") or ""))
        if not ms:
            if not row["win"]: upcoming.append(row)
            continue
        row.update(g=len(ms), maps=sum(len(m["maps"]) for m in ms), places=d.get("places") or [])
        row["a"] = row["a"] or day(ms[0]["ts"]); row["b"] = row["b"] or day(ms[-1]["ts"])
        row["live"] = not row["win"]
        tours.append(row)
        rosters[eid] = {}
        for tm, pl in (d.get("teams") or {}).items():
            ids = []
            for pid, n, cc, role in pl:
                if role and role.lower() not in ("captain", "igl", "in-game leader"): continue  # coaches, analysts, managers
                k = slug(pid); ids.append(k); pinfo[k] = [n, cc]
            rosters[eid][tm] = ids
        for i, m in enumerate(ms):
            w = m["w"] if m["w"] is not None else (0 if m["s"] and m["s"][0] > m["s"][1] else 1)
            series.append(dict(id=f"{eid}-{i + 1}", e=eid, ts=m["ts"], dt=day(m["ts"]), t=m["t"], s=m["s"], bo=m["bo"], w=w, hltv=m.get("hltv"), v=m.get("v"),
                               maps=[dict(map=x["map"], s=x["s"], h=x["h"], v=x.get("v")) for x in m["maps"]]))
    tours.sort(key=lambda t: t["b"], reverse=True)
    upcoming.sort(key=lambda t: t["a"] or t["dates"])
    tinfo = {t["id"]: t for t in tours}
    series.sort(key=lambda s: -s["ts"])

    # teams
    teams = {}
    def team(n):
        k = slug(n)
        if k not in teams:
            teams[k] = dict(id=k, n=n, sw=0, sl=0, mw=0, ml=0, rw=0, rl=0, ct=[0, 0], t=[0, 0], pool=defaultdict(lambda: [0, 0]), last="", rows=[], titles=[], prize=0, ev=set())
        return teams[k]
    map_st = defaultdict(lambda: dict(g=0, ct=0, t=0, ot=0, stomp=0))
    allmaps = []
    for s in series:
        A, B = team(s["t"][0]), team(s["t"][1])
        for side, (me, op) in enumerate(((A, B), (B, A))):
            won = s["w"] == side
            me["sw" if won else "sl"] += 1; me["last"] = max(me["last"], s["dt"]); me["ev"].add(s["e"])
            me["rows"].append(dict(id=s["id"], e=s["e"], dt=s["dt"], op=op["id"], on=op["n"], w=int(won), s=[s["s"][side], s["s"][1 - side]] if s["s"] else None,
                                   maps=[[x["map"], x["s"][side], x["s"][1 - side]] for x in s["maps"]]))
            for x in s["maps"]:
                mw = x["s"][side] > x["s"][1 - side]
                me["mw" if mw else "ml"] += 1; me["rw"] += x["s"][side]; me["rl"] += x["s"][1 - side]
                me["pool"][x["map"]][0] += 1; me["pool"][x["map"]][1] += mw
                mine, theirs = (x["h"] + [[], []])[side], (x["h"] + [[], []])[1 - side]
                for sd, r in mine[:2]: me[sd][0] += r              # regulation halves only
                for sd, r in theirs[:2]: me["t" if sd == "ct" else "ct"][1] += r
        for x in s["maps"]:
            st = map_st[x["map"]]; st["g"] += 1
            if max(x["s"]) > 13: st["ot"] += 1
            if min(x["s"]) <= 3: st["stomp"] += 1
            for h in x["h"]:
                for sd, r in h[:2]: st[sd] += r
            allmaps.append((s, x))
    for t in tours:
        for place, tm, money in t["places"]:
            k = slug(tm)
            if k in teams:
                teams[k]["prize"] += money
                if place == "1": teams[k]["titles"].append(t["id"])

    # VRS: match Valve's short names to our teams by roster overlap, then by name
    latest_ro = {}
    for t in sorted(tours, key=lambda t: t["b"]):
        for tm, ids in rosters[t["id"]].items(): latest_ro[slug(tm)] = (t["id"], ids)
    vrank = {}
    for rank, pts, vn, ro in vrs["rows"]:
        ro_n = {norm(x) for x in ro}
        best = max(((len(ro_n & {norm(pinfo.get(p, [p])[0]) for p in ids}), k) for k, (_, ids) in latest_ro.items()), default=(0, None))
        k = best[1] if best[0] >= 3 else next((k for k in teams if norm(teams[k]["n"]) == norm(vn) or norm(teams[k]["n"]).replace("team", "") == norm(vn)), None)
        if k and k not in vrank: vrank[k] = [rank, pts]

    # players: every event roster they were on, with that team's results there
    prow = defaultdict(list)
    for t in tours:
        for tm, ids in rosters[t["id"]].items():
            k = slug(tm)
            rows = [r for r in teams[k]["rows"] if r["e"] == t["id"]] if k in teams else []
            if not rows: continue
            place = next((p for p, n, _ in t["places"] if n == tm), "")
            for pid in ids:
                prow[pid].append(dict(e=t["id"], tm=k, tn=tm, place=place, sw=sum(r["w"] for r in rows), sl=sum(1 - r["w"] for r in rows),
                                      mw=sum(m[1] > m[2] for r in rows for m in r["maps"]), ml=sum(m[1] < m[2] for r in rows for m in r["maps"]),
                                      rw=sum(m[1] for r in rows for m in r["maps"]), rl=sum(m[2] for r in rows for m in r["maps"])))
    players = []
    for pid, rows in prow.items():
        rows.sort(key=lambda r: tinfo[r["e"]]["b"], reverse=True)
        tot = {k: sum(r[k] for r in rows) for k in ("sw", "sl", "mw", "ml", "rw", "rl")}
        n, cc = pinfo.get(pid, [pid, ""])
        pool = Counter()
        for r in rows:
            for x in teams[r["tm"]]["rows"]:
                if x["e"] == r["e"]:
                    for m in x["maps"]: pool[m[0]] += 1
        players.append(dict(id=pid, n=n, cc=cc, tm=rows[0]["tm"], tn=rows[0]["tn"], ev=len(rows), titles=sum(r["place"] == "1" for r in rows),
                            top4=sum(r["place"] in ("1", "2", "3", "4", "3-4") for r in rows), maps=pool.most_common(3), **tot))
        dump(out / "p" / f"{pid}.json", dict(rows=rows))

    tlist = []
    for t in teams.values():
        g = t["sw"] + t["sl"]
        ro = latest_ro.get(t["id"], (None, []))[1]
        dump(out / "t" / f"{t['id']}.json", dict(rows=t["rows"], pool={k: v for k, v in sorted(t["pool"].items(), key=lambda kv: -kv[1][0])}))
        tlist.append(dict(id=t["id"], n=t["n"], g=g, sw=t["sw"], mw=t["mw"], ml=t["ml"], rw=t["rw"], rl=t["rl"], ct=t["ct"], t=t["t"], last=t["last"], ro=ro,
                          titles=t["titles"], prize=t["prize"], ev=len(t["ev"]), vrs=vrank.get(t["id"])))
    for s in series: dump(out / "s" / f"{s['id']}.json", s)
    for t in tours:
        dump(out / "e" / f"{t['id']}.json", dict(series=[s for s in series if s["e"] == t["id"]], rosters=rosters[t["id"]]))
    dump(out / "meta.json", dict(maps={k: v for k, v in map_st.items()}))

    # season records (front page)
    rec = {}
    if allmaps:
        lng = max(allmaps, key=lambda sx: sum(sx[1]["s"]))
        zero = [sx for sx in allmaps if min(sx[1]["s"]) == 0]
        def comeback(sx):  # biggest halftime deficit turned into a win
            s, x = sx
            if len(x["h"]) < 2 or not x["h"][0] or not x["h"][1]: return (0, 0)
            a, b = x["h"][0][0][1], x["h"][1][0][1]
            w = 0 if x["s"][0] > x["s"][1] else 1
            return ((b - a) if w == 0 else (a - b), -sum(x["s"]))
        cb = max(allmaps, key=comeback)
        cbd = comeback(cb)[0]
        w = 0 if cb[1]["s"][0] > cb[1]["s"][1] else 1
        rec = dict(long=[lng[0]["id"], lng[1]["map"], lng[1]["s"], lng[0]["t"]], zeros=len(zero),
                   zero=[zero[0][0]["id"], zero[0][1]["map"], zero[0][1]["s"], zero[0][0]["t"]] if zero else None,
                   cb=[cb[0]["id"], cb[1]["map"], [cb[1]["h"][w][0][1], cb[1]["h"][1 - w][0][1]], cb[1]["s"], cb[0]["t"][w], cb[0]["t"][1 - w]] if cbd > 0 else None,
                   ot=sum(1 for _, x in allmaps if max(x["s"]) > 13))
    vrs_rows = [[r, p, n, ro, next((k for k, v in vrank.items() if v[0] == r), None)] for r, p, n, ro in vrs["rows"][:30]]
    index = dict(v=int(time.time()), n=len(series), nm=len(allmaps), tours=tours, up=upcoming, teams=sorted(tlist, key=lambda t: -t["g"]),
                 players=sorted(players, key=lambda p: -(p["mw"] + p["ml"])), rec=rec, vrs=dict(date=vrs["date"], rows=vrs_rows),
                 recent=[dict(id=s["id"], e=s["e"], dt=s["dt"], t=s["t"], s=s["s"], w=s["w"], maps=[[x["map"], x["s"]] for x in s["maps"]]) for s in series[:30]])
    dump(out / "index.json", index)
    write_pages(dist, site, index, ads)
    print(f"cs: {len(tours)} events, {len(series)} series, {len(allmaps)} maps, {len(players)} players, {len(tlist)} teams, {len(vrank)} VRS-matched")

def write_pages(dist, site, idx, ads=""):
    pages = []
    for p in idx["players"]:
        mg = p["mw"] + p["ml"]
        pages.append((f"player/{p['id']}/", f"{p['n']} ({p['tn']}) – CS2 Pro Results & Events | prostats.gg",
                      f"{p['n']} of {p['tn']} in 2026: {p['ev']} S-Tier events, {p['titles']} titles, {p['mw']}–{p['ml']} on maps. Every event and series.",
                      f"<h1>{e(p['n'])}</h1><p>{e(p['tn'])} · {p['ev']} events · {mg} maps</p>"))
    for t in idx["teams"]:
        pages.append((f"team/{t['id']}/", f"{t['n']} – CS2 Team Stats, Map Pool & Results | prostats.gg",
                      f"{t['n']} in 2026: {t['sw']}–{t['g'] - t['sw']} in series, {t['mw']}–{t['ml']} on maps, {len(t['titles'])} titles. Map pool, CT/T rounds, roster and every series.",
                      f"<h1>{e(t['n'])}</h1><p>{t['sw']}W {t['g'] - t['sw']}L series · {t['mw']}–{t['ml']} maps</p>"))
    meta = json.loads((dist / "cs" / "data" / "meta.json").read_text(encoding="utf-8"))
    for mp in meta["maps"]:
        pages.append((f"map/{slug(mp)}/", f"{mp} – CS2 Pro Map Stats, CT vs T Win Rates | prostats.gg",
                      f"{mp} in 2026 S-Tier CS2: CT vs T round win rates, overtime rate, the teams that win it most and every pro map played.", f"<h1>{e(mp)}</h1>"))
    for t in idx["tours"]:
        pages.append((f"event/{t['id']}/", f"{t['n']} – Results, Bracket & Placements | prostats.gg",
                      f"{t['n']} ({t['dates']}): every series and map, standings, placements and prize money.", f"<h1>{e(t['n'])}</h1><p>{t['g']} series · {t['maps']} maps</p>"))
    for path, t in (("maps/", "CS2 Pro Map Stats"), ("players/", "CS2 Pro Players"), ("teams/", "CS2 Team Rankings"), ("events/", "CS2 2026 S-Tier Events")):
        pages.append((path, f"{t} | prostats.gg", f"{t} from every 2026 S-Tier Counter-Strike 2 match.", f"<h1>{e(t)}</h1>"))
    pages.append(("", "prostats.gg – CS2 Pro Stats, Results & VRS Rankings",
                  "op.gg for pro Counter-Strike 2: every 2026 S-Tier series and map, team map pools, CT/T splits, placements and Valve's VRS ranking.",
                  "<h1>CS2 pro stats</h1>" + "".join(f'<a href="team/{t["id"]}/">{e(t["n"])}</a> ' for t in idx["teams"][:60])))
    val_build.write_shell(dist, site, ads, "cs", pages)
