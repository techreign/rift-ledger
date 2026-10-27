"""Static pages for search engines and link previews, written by build.py after the data.

The app is one page that routes on the URL path (player/48/, team/2809/, ...). GitHub Pages only answers 200 for files
that exist, so each player, team, champion and tournament gets a small player/<id>/index.html: the shared shell (header,
footer, app.js/app.css) with its own title, description, canonical/og tags, JSON-LD and a plain-HTML summary in #app
that the app replaces once it loads. Crawlers that don't run JS still get the summary and links to related pages.
Everything else (game pages, h2h, compare, filters) falls through to 404.html, which is the same shell.
"""
import gzip, hashlib, json, re
from collections import defaultdict
from html import escape
from urllib.parse import urlparse

ROLE = {"top": "top laner", "jungle": "jungler", "mid": "mid laner", "adc": "bot laner (ADC)", "support": "support"}
MIN_OLD = 30  # pre-2026-only players/teams need this many games for their own page

def e(x): return escape(str(x if x is not None else ""), quote=True)
def pct(w, g): return round(100 * w / g) if g else 0
def kda(k, d, a): return f"{(k + a) / max(d, 1):.2f}"
def num(n): return f"{n:,}"

def split_app(page):
    """src/app.html -> (shell before the CSS, css, markup between, js, tail)"""
    a, b = page.index("<style>"), page.index("</style>")
    c, d = page.index("<script>", b), page.index("</script>", b)
    return page[:a], page[a + 7:b], page[b + 8:c], page[c + 8:d], page[d + 9:]

def sums(by, n):
    t = [0] * n
    for v in by.values():
        for i in range(n): t[i] += v[i] or 0
    return t

def year_of(slug, tours):
    t = tours.get(slug)
    return int(t["y"]) if t and t.get("y") else int(slug[:4]) if slug[:4].isdigit() else 2026

def write_pages(dist, page, site):
    base = urlparse(site).path or "/"
    head, css, mid, js, tail = split_app(page)
    v = hashlib.md5((css + js).encode()).hexdigest()[:10]
    (dist / "app.css").write_text(css, encoding="utf-8")
    (dist / "app.js").write_text(js, encoding="utf-8")
    head = head.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n<base href="{base}">', 1)
    shell = f'{head}<link rel="stylesheet" href="app.css?v={v}">\n{mid}<script src="app.js?v={v}"></script>{tail}'
    APP = re.compile(r'(<div class="wrap" id="app">).*?(</div></main>)', re.S)

    def render(path, title, desc, body, ld=None, robots=None):
        h = re.sub(r"<title>.*?</title>", lambda m: f"<title>{e(title)}</title>", shell, count=1)
        for pat, val in ((r'(<meta name="description" content=")[^"]*', desc), (r'(<meta property="og:title" content=")[^"]*', title),
                         (r'(<meta property="og:description" content=")[^"]*', desc), (r'(<link rel="canonical" href=")[^"]*', site + path),
                         (r'(<meta property="og:url" content=")[^"]*', site + path)):
            h = re.sub(pat, lambda m: m[1] + e(val), h, count=1)
        lds = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") if ld else ""
        extra = (f'<script type="application/ld+json">{lds}</script>\n' if ld else "") + \
                (f'<meta name="robots" content="{robots}">\n' if robots else "")
        h = h.replace("</head>", extra + "</head>", 1)
        h = APP.sub(lambda m: m[1] + f'<div class="card seo">{body}</div>' + m[2], h, count=1)
        out = dist / path / "index.html" if path else dist / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(h, encoding="utf-8")

    idx = json.loads((dist / "data" / "index.json").read_text(encoding="utf-8"))
    hp = dist / "data" / "h" / "index.json.gz"
    life = json.loads(gzip.decompress(hp.read_bytes())) if hp.exists() else dict(players=[], teams=[], champs=[], tours=[])
    # per-tournament stats for earlier seasons live in one file per year (h/by/<year>.json.gz)
    for f in sorted((dist / "data" / "h" / "by").glob("*.json.gz")):
        d = json.loads(gzip.decompress(f.read_bytes()))
        for k, items, key in (("p", life["players"], "id"), ("t", life["teams"], "id"), ("c", life["champs"], "c")):
            for x in items:
                if x[key] in d[k]: x.setdefault("by", {}).update(d[k][x[key]])
    for items in (life["players"], life["teams"], life["champs"]):
        for x in items: x.setdefault("by", {})
    tours = {t["s"]: t for t in idx["tours"]}
    tours.update({t["s"]: t for t in life["tours"]})
    hplayers = {p["id"]: p for p in life["players"]}
    hteams = {t["id"]: t for t in life["teams"]}
    hchamps = {c["c"]: c for c in life["champs"]}
    teams26 = {t["id"]: t for t in idx["teams"]}
    tname = {**{t["id"]: t["n"] for t in life["teams"]}, **{t["id"]: t["n"] for t in idx["teams"]}}
    cname = {c["c"]: c["n"] for c in idx["champs"]}
    first = idx["seasons"][-1]["y"]
    urls = []
    link = lambda kind, id, n: f'<a href="{kind}/{e(id)}/">{e(n)}</a>'

    def season_rows(rows):
        """[(year, team, g, w, k, d, a)] -> table"""
        if not rows: return ""
        tr = "".join(f"<tr><td>{y}</td><td>{e(tn)}</td><td>{g}</td><td>{w}W {g - w}L</td><td>{pct(w, g)}%</td>"
                     f"<td>{kda(k, d, a) if k is not None else '–'}</td></tr>" for y, tn, g, w, k, d, a in rows)
        return f'<h2>Seasons</h2><table class="seo-t"><tr><th>Season</th><th>Team</th><th>Games</th><th>Record</th><th>Win rate</th><th>KDA</th></tr>{tr}</table>'

    def old_years(by):
        y = defaultdict(lambda: [0] * 5)
        for slug, v in by.items():
            r = y[year_of(slug, tours)]
            for i in range(5): r[i] += v[i] if i < len(v) else 0
        return y

    # ---- players
    roster = defaultdict(list)
    for p in idx["players"]:
        g, w, k, d, a = sums(p["by"], 5)
        role = ROLE.get(p.get("r"), "player")
        rows = [(2026, p.get("tn"), g, w, k, d, a)] + [(int(y), v[5], v[0], v[1], v[2], v[3], v[4]) for y, v in sorted(p.get("yrs", {}).items(), reverse=True)]
        cg, cw = sum(r[2] for r in rows), sum(r[3] for r in rows)
        top = ", ".join(cname.get(c, c) for c in p.get("top", []))
        desc = (f"{p['n']} ({p.get('tn')}, {p.get('lg')}) pro stats: {g} games in 2026, {w}W–{g - w}L ({pct(w, g)}% WR), KDA {kda(k, d, a)}."
                + (f" Most played: {top}." if top else "") + (f" Career: {num(cg)} games since {rows[-1][0]}." if len(rows) > 1 else ""))
        body = (f"<h1>{e(p['n'])}</h1><p>{e(p['n'])} is a {role} for {link('team', p['tm'], p.get('tn'))} in the {e(p.get('lg'))}. "
                f"In 2026: {g} games, {w}W–{g - w}L ({pct(w, g)}%), KDA {kda(k, d, a)} ({k / max(g, 1):.1f} / {d / max(g, 1):.1f} / {a / max(g, 1):.1f})."
                + (f" Most played champions: {e(top)}." if top else "") + (f" {num(cg)} pro games since {rows[-1][0]} ({pct(cw, cg)}% wins)." if len(rows) > 1 else "")
                + "</p>" + season_rows(rows))
        ld = {"@context": "https://schema.org", "@type": "Person", "name": p["n"], "jobTitle": "Professional League of Legends player",
              "memberOf": {"@type": "SportsTeam", "name": p.get("tn"), "sport": "League of Legends"}, **({"image": p["ph"]} if p.get("ph") else {})}
        render(f"player/{p['id']}/", f"{p['n']} ({p.get('tn')}) – Pro Stats, Champion Pool & Match History | prostats.gg", desc, body, ld)
        urls.append(f"player/{p['id']}/"); roster[p["tm"]].append(p)
    for p in life["players"]:
        if not str(p["id"]).startswith("o") or p["g"] < MIN_OLD: continue
        ys = old_years(p["by"]); g, w, k, d, a = sums(ys, 5)
        span = f"{min(ys)}–{max(ys)}" if len(ys) > 1 else str(min(ys))
        top = ", ".join(cname.get(c, c) for c in p.get("top", []))
        desc = (f"{p['n']} pro career stats ({span}): {num(g)} games, {w}W–{g - w}L ({pct(w, g)}% WR), KDA {kda(k, d, a)}, last with {p.get('tn')}."
                + (f" Most played: {top}." if top else ""))
        body = (f"<h1>{e(p['n'])}</h1><p>{e(p['n'])} played {num(g)} pro games as a {ROLE.get(p.get('r'), 'player')} ({span}), "
                f"last for {link('team', p['tm'], p.get('tn'))} in the {e(p.get('lg'))}: {w}W–{g - w}L ({pct(w, g)}%), KDA {kda(k, d, a)}."
                + (f" Most played champions: {e(top)}." if top else "") + "</p>"
                + season_rows([(y, "", v[0], v[1], v[2], v[3], v[4]) for y, v in sorted(ys.items(), reverse=True)]))
        ld = {"@context": "https://schema.org", "@type": "Person", "name": p["n"], "jobTitle": "Professional League of Legends player"}
        render(f"player/{p['id']}/", f"{p['n']} – Pro Career Stats & Match History ({span}) | prostats.gg", desc, body, ld)
        urls.append(f"player/{p['id']}/"); roster[p["tm"]].append(p)

    # ---- teams
    def team_page(id, n, lg, lo, rows, cur):
        g, w = sum(r[2] for r in rows), sum(r[3] for r in rows)
        span = f"{rows[-1][0]}–{rows[0][0]}" if len(rows) > 1 else str(rows[0][0])
        names = list(dict.fromkeys(r[1] for r in rows if r[1] and r[1] != n))
        mem = sorted(roster.get(id, []), key=lambda p: -p["g"])[:12]
        desc = (f"{n} ({lg}) pro League of Legends stats: " + (f"{cur[1]}W–{cur[0] - cur[1]}L in 2026, " if cur else "")
                + f"{num(g)} games since {rows[-1][0]} ({pct(w, g)}% wins). Roster, match history, picks and bans.")
        body = (f"<h1>{e(n)}</h1><p>{e(n)} plays in the {e(lg)}." + (f" Also known as {e(', '.join(names))}." if names else "")
                + (f" 2026 record: {cur[1]}W–{cur[0] - cur[1]}L ({pct(cur[1], cur[0])}%)." if cur else "")
                + f" {num(g)} pro games {span}, {pct(w, g)}% wins.</p>"
                + (f"<h2>{'Roster' if cur else 'Players'}</h2><ul>" + "".join(f"<li>{link('player', p['id'], p['n'])} – {ROLE.get(p.get('r'), '')}</li>" for p in mem) + "</ul>" if mem else "")
                + season_rows([(y, tn, gg, ww, None, None, None) for y, tn, gg, ww in rows]))
        ld = {"@context": "https://schema.org", "@type": "SportsTeam", "name": n, "sport": "League of Legends", **({"logo": lo} if lo else {}),
              **({"alternateName": names} if names else {}), "athlete": [{"@type": "Person", "name": p["n"]} for p in mem[:5]] if cur else []}
        render(f"team/{id}/", f"{n} – {lg} Pro Stats, Roster & Match History | prostats.gg", desc, body, ld)
        urls.append(f"team/{id}/")
    for t in idx["teams"]:
        g, w = sums(t["by"], 2)
        rows = [(2026, t["n"], g, w)] + [(int(y), v[5], v[0], v[1]) for y, v in sorted(t.get("yrs", {}).items(), reverse=True)]
        team_page(t["id"], t["n"], t.get("lg"), t.get("lo"), rows, (g, w))
    for t in life["teams"]:
        if not str(t["id"]).startswith("o") or t["g"] < MIN_OLD: continue
        ys = defaultdict(lambda: [0, 0])
        for slug, v in t["by"].items(): r = ys[year_of(slug, tours)]; r[0] += v[0]; r[1] += v[1]
        team_page(t["id"], t["n"], t.get("lg"), t.get("lo"), [(y, "", v[0], v[1]) for y, v in sorted(ys.items(), reverse=True)], None)

    # ---- champions
    for c in idx["champs"]:
        p, w, b = sums(c["by"], 3)
        ng = sum(t["g"] for t in idx["tours"])
        old = hchamps.get(c["c"]); op, ow, ob = sums(old["by"], 3) if old else (0, 0, 0)
        desc = (f"{c['n']} in 2026 pro play: picked {num(p)} times ({pct(w, p)}% win rate), banned {num(b)} times, "
                f"{pct(p + b, ng)}% pick/ban presence. Builds, matchups and best pro players.")
        body = (f"<h1>{e(c['n'])} in pro play</h1><p>In 2026, {e(c['n'])} has been picked {num(p)} times with a {pct(w, p)}% win rate and banned {num(b)} times "
                f"across {num(ng)} pro games ({pct(p + b, ng)}% presence)."
                + (f" Since {first}: {num(op + p)} picks, {pct(ow + w, op + p)}% wins, {num(ob + b)} bans." if op else "") + "</p>")
        render(f"champion/{c['c']}/", f"{c['n']} Pro Stats 2026 – Win Rate, Pick & Ban Rate, Builds | prostats.gg", desc, body)
        urls.append(f"champion/{c['c']}/")

    # ---- tournaments
    for t in list(idx["tours"]) + list(life["tours"]):
        y = t.get("y") or 2026
        desc = f"{t['n']}: {t.get('g', 0)} pro games" + (f", {t['a']} to {t['b']}" if t.get("a") else "") + ". Results, player stats, champion picks and bans."
        body = (f"<h1>{e(t['n'])}</h1><p>{e(t['n'])} ({e(t.get('lg'))}, {y}): {t.get('g', 0)} games"
                + (f" played {e(t['a'])} to {e(t['b'])}" if t.get("a") else "") + ".</p>")
        ld = {"@context": "https://schema.org", "@type": "SportsEvent", "name": t["n"], "sport": "League of Legends",
              **({"startDate": t["a"], "endDate": t["b"]} if t.get("a") else {})}
        render(f"t/{t['s']}/", f"{t['n']} – Results, Player & Champion Stats | prostats.gg", desc, body, ld)
        urls.append(f"t/{t['s']}/")

    render("privacy/", "Privacy – prostats.gg", "How prostats.gg handles data: no accounts, local storage for recent searches, Google AdSense cookies.",
           "<h1>Privacy</h1><p>prostats.gg has no accounts. Recent searches and favourites stay in your browser. Ads are served by Google AdSense, "
           "which uses cookies; opt out at https://adssettings.google.com.</p>")
    urls.append("privacy/")

    # ---- home (links into everything above) and the fallback for every other path
    tp = sorted(idx["players"], key=lambda p: -p["g"])[:60]
    home = (f"<h1>prostats.gg – every pro League of Legends game</h1><p>Match histories, champion pools, builds, tier lists and head-to-heads for "
            f"{num(idx['n'])} pro games in 2026 and {num(sum(s['n'] for s in idx['seasons'][1:]))} more since {first}.</p>"
            + "<h2>Players</h2><p>" + " · ".join(link("player", p["id"], p["n"]) for p in tp) + "</p>"
            + "<h2>Teams</h2><p>" + " · ".join(link("team", t["id"], t["n"]) for t in sorted(idx["teams"], key=lambda t: -t["g"])[:60]) + "</p>"
            + "<h2>Champions</h2><p>" + " · ".join(link("champion", c["c"], c["n"]) for c in idx["champs"]) + "</p>"
            + "<h2>Tournaments</h2><p>" + " · ".join(link("t", t["s"], t["n"]) for t in idx["tours"]) + "</p>")
    render("", "prostats.gg – Pro League of Legends Stats, Match History & Tier List",
           f"op.gg for pro play: match histories, champion pools, builds, tier list and leaderboards for every pro LoL game since {first}.", home)
    nf = APP.sub(lambda m: m[1] + '<div class="loading">Loading…</div>' + m[2], shell, count=1)
    dota = base + "dota/"
    nf = nf.replace("</head>", '<script>if(location.pathname.indexOf("' + dota + '")===0)location.replace("' + dota + '#/"'
                    '+location.pathname.slice(' + str(len(dota)) + ').replace(/[/]$/,"")+location.search)</script>\n</head>', 1)
    (dist / "404.html").write_text(nf, encoding="utf-8")

    sm = "".join(f"<url><loc>{e(site + u)}</loc></url>" for u in [""] + urls)
    (dist / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>\n', encoding="utf-8")
    print(f"seo: {len(urls) + 1} pages")
