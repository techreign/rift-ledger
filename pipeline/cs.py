"""Counter-Strike 2 pro matches (2026 S-Tier) from Liquipedia (CC-BY-SA 3.0) + Valve's VRS standings.

  python pipeline/cs.py [--minutes 30]

Liquipedia (https://liquipedia.net/api-terms-of-use): custom User-Agent, gzip, 1 request / 2 s, action=parse
at most 1 / 30 s, cache everything. Pages are only re-parsed when their revision id changed.
  - "S-Tier Tournaments": the 2026 events (dates, prize, location, winner) -> data/cs/tours.json
  - each event page (+ its Stage / Playoffs subpages): every match popup -> date, teams, series score,
    maps with round scores by half and side, per-map VODs, HLTV links; participants with rosters;
    prize pool placements -> data/cs/m/<event slug>.json
Valve (github.com/ValveSoftware/counter-strike_regional_standings): the latest global VRS ranking -> data/cs/vrs.json
There is no free, allowed source of per-map player stats (HLTV forbids scraping), so the site links to HLTV.
"""
import argparse, html, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
from val import http, slug, txt

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "cs"
LP = "https://liquipedia.net/counterstrike/api.php"
VRS = "https://api.github.com/repos/ValveSoftware/counter-strike_regional_standings/contents/live/"
SUB_RE = re.compile(r"^(?:Stage \d|Playoffs|Group Stage|Play-In|Main Event|Online Stage(?:/Stage \d)?)$")
last = {"q": 0.0, "p": 0.0}

def lp(params, parse=False):
    """Liquipedia API call, spaced per their terms (2 s, 30 s for action=parse)"""
    gap, k = (31, "p") if parse else (2.2, "q")
    wait = max(last[k] + gap, last["q"] + 2.2) - time.time()
    if wait > 0: time.sleep(wait)
    try: return http(LP + "?" + urllib.parse.urlencode({**params, "format": "json"}))
    finally: last[k] = last["q"] = time.time()

def parse(page): return html.unescape(lp(dict(action="parse", page=page, prop="text"), parse=True)["parse"]["text"]["*"])

def parse_tiers(h):
    out = []
    for r in re.split(r'<tr class="table2__row--body', h)[1:]:
        a = re.search(r'class="column__tournament"[^>]*><a href="/counterstrike/([^"]+)"[^>]*>([^<]+)', r)
        td = [re.sub(r"\s+", " ", txt(x)) for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if not a or len(td) < 9 or "2026" not in td[3] or "Cancelled" in td[7]: continue
        out.append(dict(page=urllib.parse.unquote(a[1]).replace("_", " "), name=html.unescape(a[2]), dates=td[3].replace("�", "–"),
                        prize=td[4], loc=td[5], n=td[6], win=td[7] if td[7] != "TBD" else None, second=td[8] if td[8] != "TBD" else None))
    return out

def parse_matches(h):
    """every match popup on a rendered event page"""
    out, seen = [], set()
    for pop in re.split(r'<div class="brkts-popup brkts-popup-container brkts-match-info-popup"', h)[1:]:
        ts = re.search(r'data-timestamp="(\d+)"', pop)
        head = pop.split('class="brkts-popup-body"')[0]
        names = re.findall(r'<span class="name[^"]*"[^>]*><a [^>]*title="([^"]+)"', head)
        sc = re.findall(r'scoreholder-score(?: match-info-header-winner)?">(\d*)<', head)
        if not ts or len(names) < 2: continue
        key = (ts[1], names[0], names[1])
        if key in seen: continue
        seen.add(key)
        bo = re.search(r"\(Bo(\d)\)", head)
        maps = []
        for row in re.split(r'<div class="brkts-popup-body-grid-row">', pop)[1:]:
            mp = re.search(r'<div class="brkts-popup-spaced"><a [^>]*title="([^"]+)"', row)
            sides = re.split(r'brkts-popup-body-detailed-scores-container', row)
            if not mp or len(sides) < 3: continue
            sc2, halves = [], []
            for part in sides[1:3]:
                main = re.search(r'main-score">([^<]*)<', part)
                sc2.append(main[1] if main else "")
                halves.append([[s[0], int(s[1])] for s in re.findall(r'brkts-cs-score-color-(ct|t)">(\d*)<', part) if s[1]])
            try: s1, s2 = int(sc2[0]), int(sc2[1])
            except ValueError: continue  # map not played
            maps.append(dict(map=mp[1], s=[s1, s2], h=halves))
        foot = pop.split("brkts-popup-footer")[-1]
        vods = dict((int(g), u) for g, u in re.findall(r'title="Watch Game (\d+)"><a href="([^"]+)"', foot))
        hltv = re.search(r'hltv\.org/matches/(\d+)', foot)
        for i, m in enumerate(maps): m["v"] = vods.get(i + 1)
        win = 0 if "match-info-header-opponent-left match-info-header-winner" in head else 1 if re.search(r'match-info-header-opponent match-info-header-winner', head) else None
        try: s = [int(sc[0]), int(sc[1])]
        except (ValueError, IndexError):  # no series score shown: count map wins
            s = [sum(m["s"][0] > m["s"][1] for m in maps), sum(m["s"][1] > m["s"][0] for m in maps)] if maps else None
        if not maps and not s: continue
        out.append(dict(ts=int(ts[1]), t=names[:2], s=s, bo=int(bo[1]) if bo else None, w=win, maps=maps,
                        v=vods.get(0) or (next(iter(vods.values())) if vods and not maps else None), hltv=hltv[1] if hltv else None))
    return sorted(out, key=lambda m: m["ts"])

def parse_teams(h):
    """participant cards: team -> players [id, name, country, role]"""
    out = {}
    for c in re.split(r'<div class="general-collapsible collapsed team-participant-card">', h)[1:]:
        tm = re.search(r'<span class="name"[^>]*><a [^>]*title="([^"]+)"', c)
        if not tm or tm[1] in out: continue
        pl = []
        for m in re.split(r'class="team-participant-card__member"', c)[1:]:
            a = re.search(r'<a href="/counterstrike/([^"]+)" title="([^"]+)">([^<]+)</a>', m)
            if not a: continue
            cc = re.search(r'<span class="flag"><img alt="([^"]*)"', m)
            role = re.search(r'member-role[^>]*>([^<]+)<', m)
            pl.append([urllib.parse.unquote(a[1]), a[3], cc[1] if cc else "", role[1].strip() if role else ""])
        out[tm[1]] = pl
    return out

def parse_places(h):
    out, place = [], None
    for r in re.split(r'<tr class="table2__row--body', h.split('id="Prize_Pool"')[-1].split("prizepool-section-wrapper")[1] if 'id="Prize_Pool"' in h else "")[1:]:
        b = re.search(r'<td class="prizepooltable-place"[^>]*>(.*?)</td>', r, re.S)
        money = re.search(r'<td data-align="right"[^>]*>\$([\d,]+)', r)
        if b: place, prize = txt(b[1]), int(money[1].replace(",", "")) if money else 0  # place and prize span the tied rows
        tm = re.search(r'<span class="name"[^>]*><a [^>]*title="([^"]+)"', r)
        if tm and place: out.append([place, tm[1], prize])
        if "</table>" in r: break
    return out

def info(h):
    out = {}
    for k in ("Start Date", "End Date", "Prize Pool", "Location", "Venue", "Type", "Organizer", "Teams"):
        v = re.search(rf'<div class="infobox-cell-2 infobox-description">{k}:</div><div[^>]*>(.*?)</div>', h, re.S)
        if v: out[k] = re.sub(r"\s+", " ", txt(v[1])).strip()
    return out

def vrs():
    """Valve's latest global ranking (published monthly)"""
    p = D / "vrs.json"
    if p.exists() and time.time() - p.stat().st_mtime < 86400: return
    files = [f["name"] for f in http(VRS + "2026") if f["name"].startswith("standings_global_")]
    name = max(files)
    md = urllib.request.urlopen(urllib.request.Request(f"https://raw.githubusercontent.com/ValveSoftware/counter-strike_regional_standings/main/live/2026/{name}",
                                                       headers={"User-Agent": "prostats.gg"}), timeout=60).read().decode()
    rows = [[int(r[0]), int(r[1]), r[2].strip(), [x.strip() for x in r[3].split(",")]]
            for r in re.findall(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|", md, re.M)]
    p.write_text(json.dumps(dict(date=name[17:27].replace("_", "-"), rows=rows[:100]), ensure_ascii=False), encoding="utf-8")
    print(f"vrs: {name}, {len(rows)} teams")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--minutes", type=float, default=30); a = ap.parse_args()
    stop = time.time() + a.minutes * 60
    last["p"] = time.time()  # val.py may have just parsed; keep 30 s between parses across both scripts
    (D / "m").mkdir(parents=True, exist_ok=True)
    try: vrs()
    except Exception as e: print("vrs failed:", e, file=sys.stderr)
    rp, tp = D / "revs.json", D / "tours.json"
    seen = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    tier = lp(dict(action="query", prop="info", titles="S-Tier Tournaments"))["query"]["pages"]
    tier = next(iter(tier.values()))["lastrevid"]
    if seen.get("S-Tier Tournaments") != tier or not tp.exists():
        tp.write_text(json.dumps(parse_tiers(parse("S-Tier Tournaments")), indent=0, ensure_ascii=False), encoding="utf-8")
        seen["S-Tier Tournaments"] = tier
    tours = json.loads(tp.read_text(encoding="utf-8"))
    pages = {}
    for t in tours:  # Stage / Playoffs subpages; skip qualifiers and regional closed events
        sub = lp(dict(action="query", list="allpages", apprefix=t["page"] + "/", aplimit=100))["query"]["allpages"]
        pages[t["page"]] = [t["page"]] + [s["title"] for s in sub if SUB_RE.match(s["title"][len(t["page"]) + 1:])]
    want = [x for v in pages.values() for x in v]
    revs = {}
    for i in range(0, len(want), 50):
        q = lp(dict(action="query", prop="info", titles="|".join(want[i:i + 50])))
        revs.update({p["title"]: p.get("lastrevid") for p in q["query"]["pages"].values()})
    for t in tours:
        mf = D / "m" / f"{slug(t['page'])}.json"
        changed = [x for x in pages[t["page"]] if x in revs and seen.get(x) != revs[x]]
        if not changed or time.time() > stop: continue
        ms, teams, places, inf = [], {}, [], {}
        for x in pages[t["page"]]:
            h = parse(x)
            ms += parse_matches(h)
            for k, v in parse_teams(h).items(): teams.setdefault(k, v)
            if x == t["page"]: places, inf = parse_places(h), info(h)
        uniq = {}
        for m in ms: uniq[(m["ts"], *m["t"])] = m
        mf.write_text(json.dumps(dict(title=t["page"], info=inf, teams=teams, places=places, matches=sorted(uniq.values(), key=lambda m: m["ts"])),
                                 separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        for x in changed: seen[x] = revs[x]
        rp.write_text(json.dumps(seen, indent=0), encoding="utf-8")
        print(f"{t['page']}: {len(uniq)} matches, {sum(len(m['maps']) for m in uniq.values())} maps, {len(teams)} teams", flush=True)
    rp.write_text(json.dumps(seen, indent=0), encoding="utf-8")
    done = sum(1 for t in tours if (D / "m" / f"{slug(t['page'])}.json").exists())
    print(f"cs2: {len(tours)} events, {done} fetched")

if __name__ == "__main__":
    main()
