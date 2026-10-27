"""Dota 2 section of prostats.gg: data/dota (from dota.py) -> dist/dota/data + the dota app shell and SEO pages.

Called from build.py after the LoL build; skips quietly when there are no Dota matches or constants yet.
  index.json   players / teams / heroes / items / leagues / latest matches
  p/<account>.json, t/<team>.json, h/<hero>.json, l/<league>.json   rows for each page
  m/<match>.json   one match (scoreboard, picks and bans, gold graph, build orders)
  meta.json    hero picks / wins / bans per league (tier list)
"""
import hashlib, html, json, re, shutil, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "dota"
CDN = "https://cdn.cloudflare.steamstatic.com"
e = lambda s: html.escape(str(s), quote=True)

def load(name):
    p = SRC / "const" / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def positions(team):
    """Dota positions 1-5 for one side: mid = mid-lane core; the other two cores (top net worth) are 1 (safe lane) and
    3 (off lane); of the two supports the richer one is 4. Falls back to net-worth order when lanes weren't parsed."""
    order = sorted(team, key=lambda p: -(p.get("net_worth") or p.get("gold_per_min") or 0))
    cores, sups = order[:3], order[3:]
    pos = {}
    mid = next((p for p in cores if p.get("lane_role") == 2), None)
    if mid is None or not all(p.get("lane_role") for p in cores):
        for i, p in enumerate(order): pos[id(p)] = (1, 2, 3, 4, 5)[i]
        return pos
    pos[id(mid)] = 2
    rest = [p for p in cores if p is not mid]
    safe = next((p for p in rest if p.get("lane_role") == 1), rest[0])
    for p in rest: pos[id(p)] = 1 if p is safe else 3
    pos[id(sups[0])], pos[id(sups[1])] = 4, 5
    return pos

def score(m):
    """0-10 match score per player (KDA, kill participation, damage + net worth share, win), plus rank in the match"""
    sides = [[p for p in m["players"] if p["player_slot"] < 128], [p for p in m["players"] if p["player_slot"] >= 128]]
    for si, team in enumerate(sides):
        tk = sum(p.get("kills", 0) for p in team) or 1
        td = sum(p.get("hero_damage", 0) for p in team) or 1
        tn = sum(p.get("net_worth", 0) for p in team) or 1
        win = m["radiant_win"] == (si == 0)
        for p in team:
            k, d, a = p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0)
            kda = min((k + a) / max(1, d), 12) / 12
            raw = 2.5 * kda + 2.5 * min(1, (k + a) / tk) + 2 * min(1, 4 * p.get("hero_damage", 0) / td) + 1.5 * min(1, 4 * p.get("net_worth", 0) / tn) + 1.5 * win
            p["_sc"] = round(min(10, raw * 10 / 8.5), 1)
            p["_kp"] = round(100 * (k + a) / tk)
    ranked = sorted(m["players"], key=lambda p: -p["_sc"])
    for i, p in enumerate(ranked): p["_rk"] = i + 1
    for team in sides:
        best = max(team, key=lambda p: p["_sc"]); best["_tb"] = 1

def build(dist, site, ads=""):
    files = sorted((SRC / "m").glob("*.json")) if (SRC / "m").exists() else []
    heroes, item_ids, items, pros, teams_c, leagues_c = (load(n) for n in ("heroes", "item_ids", "items", "pro_players", "teams", "leagues"))
    if not files or not heroes or not item_ids:
        print("dota: no data yet, skipped"); return
    out = dist / "dota" / "data"
    if out.exists(): shutil.rmtree(out)
    for d in ("p", "t", "h", "l", "m"): (out / d).mkdir(parents=True)
    pro = {p["account_id"]: p for p in pros or []}
    tlogo = {t["team_id"]: t.get("logo_url") for t in teams_c or []}
    ltier = {l["leagueid"]: l.get("tier") for l in leagues_c or []}
    hkey = {int(k): v["name"].replace("npc_dota_hero_", "") for k, v in heroes.items()}

    matches = []
    for f in files:
        m = json.loads(f.read_text(encoding="utf-8"))
        if len(m.get("players") or []) != 10 or m.get("radiant_win") is None: continue
        matches.append(m)
    matches.sort(key=lambda m: -m["start_time"])

    prow, trow, hrow, lrow = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    pinfo, tinfo, linfo = {}, {}, {}
    hstat = defaultdict(lambda: [0, 0, 0])          # (hero, league) -> picks, wins, bans
    hitems = defaultdict(Counter)                    # hero -> finished items
    for m in matches:
        lid = m["leagueid"]; lname = (m.get("league") or {}).get("name") or f"League {lid}"
        dt = datetime.fromtimestamp(m["start_time"], timezone.utc).strftime("%Y-%m-%d")
        li = linfo.setdefault(lid, dict(id=lid, n=lname, tier=ltier.get(lid) or (m.get("league") or {}).get("tier"), g=0, a=dt, b=dt))
        li["g"] += 1; li["a"] = min(li["a"], dt); li["b"] = max(li["b"], dt)
        score(m)
        sides = [[p for p in m["players"] if p["player_slot"] < 128], [p for p in m["players"] if p["player_slot"] >= 128]]
        tms = [m.get("radiant_team") or {}, m.get("dire_team") or {}]
        for si in (0, 1):
            pos = positions(sides[si])
            for p in sides[si]: p["_pos"] = pos[id(p)]
            sides[si].sort(key=lambda p: p["_pos"])
        tid = [t.get("team_id") or f"x{m['match_id']}{i}" for i, t in enumerate(tms)]
        tnm = [t.get("name") or t.get("tag") or ("Radiant", "Dire")[i] for i, t in enumerate(tms)]
        ln = [[[p.get("account_id") or 0, p["hero_id"]] for p in s] for s in sides]
        kills = [m.get("radiant_score") or 0, m.get("dire_score") or 0]
        for pb in m.get("picks_bans") or []:
            if not pb.get("is_pick"): hstat[(pb["hero_id"], lid)][2] += 1
        for si in (0, 1):
            win = int(m["radiant_win"] == (si == 0))
            t = tms[si]
            if t.get("team_id"):
                ti = tinfo.setdefault(t["team_id"], dict(id=t["team_id"], n=tnm[si], tag=t.get("tag") or "", lo=t.get("logo_url") or tlogo.get(t["team_id"]), g=0, w=0, lgs=Counter(), last=dt))
                ti["g"] += 1; ti["w"] += win; ti["lgs"][lname] += 1
                trow[t["team_id"]].append(dict(m=m["match_id"], l=lid, dt=dt, dur=m["duration"], w=win, s=si, k=kills[si], ok=kills[1 - si], op=tid[1 - si], on=tnm[1 - si],
                    pk=[p["hero_id"] for p in sides[si]], opk=[p["hero_id"] for p in sides[1 - si]], ro=[[p.get("account_id") or 0, (pro.get(p.get("account_id")) or {}).get("name") or p.get("name") or p.get("personaname") or "?", p["_pos"]] for p in sides[si]]))
            for p in sides[si]:
                acc = p.get("account_id")
                hstat[(p["hero_id"], lid)][0] += 1; hstat[(p["hero_id"], lid)][1] += win
                its = [p.get(f"item_{i}") or 0 for i in range(6)]
                for it in its:
                    key = item_ids.get(str(it))
                    if it and (items.get(key) or {}).get("cost", 0) >= 1800: hitems[p["hero_id"]][it] += 1
                mk = max((int(k) for k in (p.get("multi_kills") or {})), default=0)
                row = dict(m=m["match_id"], l=lid, dt=dt, dur=m["duration"], w=win, h=p["hero_id"], k=p.get("kills", 0), d=p.get("deaths", 0), a=p.get("assists", 0),
                    lh=p.get("last_hits", 0), dn=p.get("denies", 0), gpm=p.get("gold_per_min", 0), xpm=p.get("xp_per_min", 0), dmg=p.get("hero_damage", 0),
                    nw=p.get("net_worth", 0), lvl=p.get("level", 0), it=its, nu=p.get("item_neutral") or 0, pos=p["_pos"], s=si, tm=tid[si], tn=tnm[si],
                    op=tid[1 - si], on=tnm[1 - si], ln=ln, sc=p["_sc"], rk=p["_rk"], kp=p["_kp"], **({"tb": 1} if p.get("_tb") else {}),
                    **({"mk": mk} if mk >= 2 else {}), **({"fb": 1} if p.get("firstblood_claimed") else {}),
                    **({"ag": 1} if p.get("aghanims_scepter") else {}), **({"sh": 1} if p.get("aghanims_shard") else {}))
                hrow[p["hero_id"]].append(dict(row, p=acc or 0, pn=(pro.get(acc) or {}).get("name") or p.get("name") or p.get("personaname") or "?"))
                if not acc: continue
                prow[acc].append(row)
                pi = pinfo.setdefault(acc, dict(id=acc, n=(pro.get(acc) or {}).get("name") or p.get("name") or p.get("personaname") or str(acc),
                    av=(pro.get(acc) or {}).get("avatarmedium"), cc=(pro.get(acc) or {}).get("country_code") or "", tm=tid[si], tn=tnm[si],
                    g=0, w=0, k=0, d=0, a=0, lh=0, gpm=0, xpm=0, dmg=0, sec=0, sc=0, pos=Counter(), hs=Counter(), lgs=Counter()))
                pi["g"] += 1; pi["w"] += win; pi["sec"] += m["duration"]; pi["sc"] += p["_sc"]
                for k2, src in (("k", "kills"), ("d", "deaths"), ("a", "assists"), ("lh", "last_hits"), ("gpm", "gold_per_min"), ("xpm", "xp_per_min"), ("dmg", "hero_damage")):
                    pi[k2] += p.get(src, 0)
                pi["pos"][p["_pos"]] += 1; pi["hs"][p["hero_id"]] += 1; pi["lgs"][lname] += 1
        lrow[lid].append(dict(m=m["match_id"], dt=dt, st=m["start_time"], dur=m["duration"], sr=m.get("series_id"), w=0 if m["radiant_win"] else 1,
            tm=[[tid[i], tnm[i], kills[i], [p["hero_id"] for p in sides[i]]] for i in (0, 1)]))
        # the match file the game page reads
        g = dict(id=m["match_id"], l=lid, ln=lname, st=m["start_time"], dur=m["duration"], rw=int(m["radiant_win"]), pa=m.get("patch"), sr=m.get("series_id"),
            tm=[dict(id=tid[i], n=tnm[i], lo=tms[i].get("logo_url") or tlogo.get(tms[i].get("team_id")), k=kills[i]) for i in (0, 1)],
            pb=[[x["hero_id"], int(x["is_pick"]), x["team"], x["order"]] for x in m.get("picks_bans") or []],
            ga=m.get("radiant_gold_adv") or [], xa=m.get("radiant_xp_adv") or [],
            pl=[dict(id=p.get("account_id") or 0, n=(pro.get(p.get("account_id")) or {}).get("name") or p.get("name") or p.get("personaname") or "?",
                h=p["hero_id"], s=si, pos=p["_pos"], **{k2: p.get(src, 0) for k2, src in (("k", "kills"), ("d", "deaths"), ("a", "assists"), ("lh", "last_hits"), ("dn", "denies"),
                ("gpm", "gold_per_min"), ("xpm", "xp_per_min"), ("dmg", "hero_damage"), ("td", "tower_damage"), ("hh", "hero_healing"), ("nw", "net_worth"), ("lvl", "level"),
                ("obs", "obs_placed"), ("sen", "sen_placed"), ("stk", "camps_stacked"))}, st=round(p.get("stuns") or 0, 1),
                it=[p.get(f"item_{i}") or 0 for i in range(6)], bp=[p.get(f"backpack_{i}") or 0 for i in range(3)], nu=p.get("item_neutral") or 0,
                ag=int(bool(p.get("aghanims_scepter"))), sh=int(bool(p.get("aghanims_shard"))), sc=p["_sc"], rk=p["_rk"], kp=p["_kp"], tb=int(bool(p.get("_tb"))),
                bu=p.get("buys") or []) for si in (0, 1) for p in sides[si]])
        (out / "m" / f"{m['match_id']}.json").write_text(json.dumps(g, separators=(",", ":")), encoding="utf-8")

    dump = lambda p, o: p.write_text(json.dumps(o, separators=(",", ":")), encoding="utf-8")
    for acc, rows in prow.items(): dump(out / "p" / f"{acc}.json", dict(n=pinfo[acc]["n"], rows=rows))
    for t, rows in trow.items(): dump(out / "t" / f"{t}.json", dict(n=tinfo[t]["n"], rows=rows))
    for lid, rows in lrow.items(): dump(out / "l" / f"{lid}.json", dict(n=linfo[lid]["n"], rows=rows))
    for h, rows in hrow.items():
        dump(out / "h" / f"{h}.json", dict(rows=rows[:300], items=[i for i, _ in hitems[h].most_common(12)]))
    lids = sorted(linfo, key=lambda l: -linfo[l]["g"])
    li_idx = {l: i for i, l in enumerate(lids)}
    dump(out / "meta.json", dict(leagues=lids, h=[[h, li_idx[l], *v] for (h, l), v in hstat.items()]))

    players = []
    for pi in pinfo.values():
        if pi["g"] < 3: continue
        players.append(dict(id=pi["id"], n=pi["n"], av=pi["av"], cc=pi["cc"], tm=pi["tm"], tn=pi["tn"], pos=pi["pos"].most_common(1)[0][0],
            lg=pi["lgs"].most_common(1)[0][0], top=[h for h, _ in pi["hs"].most_common(3)],
            s=[pi[k] for k in ("g", "w", "k", "d", "a", "lh", "gpm", "xpm", "dmg", "sec")], sc=round(pi["sc"] / pi["g"], 2)))
    teams = [dict(id=t["id"], n=t["n"], tag=t["tag"], lo=t["lo"], g=t["g"], w=t["w"], lg=t["lgs"].most_common(1)[0][0], last=t["last"]) for t in tinfo.values() if t["g"] >= 3]
    kid = {v: int(k) for k, v in item_ids.items()}
    used = {i for r in prow.values() for x in r for i in x["it"] + [x["nu"]]} | {i for c in hitems.values() for i in c} \
        | {kid[k] for m in matches for p in m["players"] for _, k in p.get("buys") or [] if k in kid}
    index = dict(built=matches[0]["start_time"], n=len(matches), v=int(time.time()), cdn=CDN,
        heroes={h: [v["localized_name"], hkey[int(h)], v.get("primary_attr"), v.get("roles") or []] for h, v in heroes.items()},
        items={i: [item_ids[str(i)], (items.get(item_ids[str(i)]) or {}).get("dname") or item_ids[str(i)]] for i in sorted(used) if i and str(i) in item_ids},
        players=players, teams=teams, leagues=[linfo[l] for l in lids],
        recent=sorted((dict(r, l=lid) for lid in lids for r in lrow[lid][:8]), key=lambda r: -r["st"])[:40])
    dump(out / "index.json", index)

    write_pages(dist, site, index, linfo, ads)
    print(f"dota: {len(matches)} matches, {len(players)} players, {len(teams)} teams, {len(linfo)} leagues")

def write_pages(dist, site, idx, linfo, ads=""):
    """dota/index.html shell + a static page per player / team / hero / league for search engines, and dota/sitemap.xml"""
    src = (ROOT / "src" / "dota.html").read_text(encoding="utf-8")
    base = re.sub(r"^https?://[^/]+", "", site) or "/"
    js_a, js_b = src.index("<script>"), src.index("</script>")
    css_a, css_b = src.index("<style>"), src.index("</style>")
    js, css = src[js_a + 8:js_b], src[css_a + 7:css_b]
    v = hashlib.md5((js + css).encode()).hexdigest()[:10]
    lol_css = (dist / "app.css").read_text(encoding="utf-8")
    (dist / "dota" / "dota.js").write_text(js, encoding="utf-8")
    (dist / "dota" / "dota.css").write_text(lol_css + "\n" + css, encoding="utf-8")
    shell = (src[:css_a] + f'<link rel="stylesheet" href="dota.css?v={v}">' + src[css_b + 8:js_a] + f'<script src="dota.js?v={v}"></script>' + src[js_b + 9:])
    shell = shell.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n<base href="{base}dota/">', 1)
    # same AdSense tags as the LoL pages (build.py adds them once ADSENSE is set)
    tags = re.findall(r'<meta name="(?:google-adsense-account|ad-slot)"[^>]*>|<script async src="https://pagead2[^>]*></script>', ads)
    shell = shell.replace("</head>", "".join(tags) + "\n</head>", 1)
    APP = re.compile(r'(<div class="wrap" id="app">).*?(</div></main>)', re.S)
    urls = []

    def render(path, title, desc, body):
        h = re.sub(r"<title>.*?</title>", lambda m: f"<title>{e(title)}</title>", shell, count=1)
        for pat, val in ((r'(<meta name="description" content=")[^"]*', desc), (r'(<meta property="og:title" content=")[^"]*', title),
                         (r'(<meta property="og:description" content=")[^"]*', desc), (r'(<link rel="canonical" href=")[^"]*', site + "dota/" + path),
                         (r'(<meta property="og:url" content=")[^"]*', site + "dota/" + path)):
            h = re.sub(pat, lambda m: m[1] + e(val), h, count=1)
        h = APP.sub(lambda m: m[1] + f'<div class="card seo">{body}</div>' + m[2], h, count=1)
        o = dist / "dota" / path / "index.html" if path else dist / "dota" / "index.html"
        o.parent.mkdir(parents=True, exist_ok=True); o.write_text(h, encoding="utf-8")
        urls.append("dota/" + path)

    POS = {1: "Carry", 2: "Mid", 3: "Offlane", 4: "Soft support", 5: "Hard support"}
    for p in idx["players"]:
        g, w, k, d, a = p["s"][:5]
        render(f"player/{p['id']}/", f"{p['n']} ({p['tn']}) – Dota 2 Pro Stats, Heroes & Match History | prostats.gg",
               f"{p['n']}, {POS[p['pos']]} for {p['tn']}: {g} pro matches in 2026, {round(100 * w / g)}% win rate, KDA {(k + a) / max(1, d):.2f}. Every pro match, hero pool and builds.",
               f"<h1>{e(p['n'])}</h1><p>{e(POS[p['pos']])} · {e(p['tn'])} · {e(p['lg'])}</p><p>{g} matches · {w}W {g - w}L · {k / g:.1f} / {d / g:.1f} / {a / g:.1f}</p>")
    for t in idx["teams"]:
        render(f"team/{t['id']}/", f"{t['n']} – Dota 2 Team Stats & Matches | prostats.gg",
               f"{t['n']}: {t['g']} pro Dota 2 matches in 2026, {round(100 * t['w'] / t['g'])}% win rate. Roster, hero picks and every match.",
               f"<h1>{e(t['n'])}</h1><p>{t['g']} matches · {t['w']}W {t['g'] - t['w']}L · {e(t['lg'])}</p>")
    for h, (name, *_r) in idx["heroes"].items():
        render(f"hero/{h}/", f"{name} – Dota 2 Pro Builds, Win Rate & Players | prostats.gg",
               f"{name} in pro Dota 2: pick, ban and win rate, core items and the pros who play it best.", f"<h1>{e(name)}</h1>")
    for l in linfo.values():
        render(f"league/{l['id']}/", f"{l['n']} – Dota 2 Results, Standings & Stats | prostats.gg",
               f"{l['n']}: every match, standings, hero picks and player stats ({l['g']} matches, {l['a']} to {l['b']}).", f"<h1>{e(l['n'])}</h1><p>{l['g']} matches</p>")
    for path, t in (("heroes/", "Dota 2 Pro Hero Tier List"), ("players/", "Dota 2 Pro Player Rankings"), ("teams/", "Dota 2 Pro Teams"), ("leagues/", "Dota 2 Tournaments")):
        render(path, f"{t} | prostats.gg", f"{t} from every 2026 pro Dota 2 match.", f"<h1>{e(t)}</h1>")
    render("", "prostats.gg – Dota 2 Pro Stats, Match History & Hero Tier List",
           "op.gg for pro Dota 2: every 2026 pro match, player match histories, hero pools, builds and a pro hero tier list.",
           "<h1>Dota 2 pro stats</h1>" + "".join(f'<a href="player/{p["id"]}/">{e(p["n"])}</a> ' for p in sorted(idx["players"], key=lambda p: -p["s"][0])[:80]))
    sm = "".join(f"<url><loc>{e(site + u)}</loc></url>" for u in urls)
    (dist / "dota" / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>\n', encoding="utf-8")
