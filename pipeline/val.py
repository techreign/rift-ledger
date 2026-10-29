"""Valorant pro matches (VCT 2026 tier 1) from Liquipedia (CC-BY-SA 3.0) + Riot's Valorant esports API.

  python pipeline/val.py [--minutes 30]

Liquipedia (https://liquipedia.net/api-terms-of-use): custom User-Agent, gzip, 1 request / 2 s, action=parse
at most 1 / 30 s, cache everything. Pages are only re-parsed when their revision id changed.
  - tournament pages (+ "/Group Stage" subpages): every match popup -> date, teams, series score, maps with
    round scores (by half and side) and both team comps -> data/val/m/<tournament slug>.json
  - "/Statistics" pages: per-player tournament totals (ACS, ADR, K/D/A, first kills/deaths, KAST, agents)
    -> data/val/s/<tournament slug>.json
Riot esports API (same public key as lolesports): team logos + per-map VOD links -> data/val/riot.json
valorant-api.com: agent and map art -> data/val/const.json
"""
import argparse, gzip, html, json, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "val"
LP = "https://liquipedia.net/valorant/api.php"
UA = "prostats.gg/0.1 (https://github.com/techreign/rift-ledger/issues)"
RIOT = "https://esports-api.service.valorantesports.com/persisted/val/"
KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
TOUR_RE = re.compile(r"^VCT/2026/(?:(?:Americas|China|EMEA|Pacific) League/(?:Kickoff|Stage 1|Stage 2|Clash)|Stage [12]/Masters|Champions)$")
last = {"q": 0.0, "p": 0.0}

def http(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
    for attempt in range(4):
        try:
            r = urllib.request.urlopen(req, timeout=60); b = r.read()
            return json.loads(gzip.decompress(b) if r.headers.get("Content-Encoding") == "gzip" else b)
        except Exception as e:
            if attempt == 3: raise
            print("retry", url[:90], e, file=sys.stderr); time.sleep(10 * (attempt + 1))

def lp(params, parse=False):
    """Liquipedia API call, spaced per their terms (2 s, 30 s for action=parse)"""
    gap, k = (31, "p") if parse else (2.2, "q")
    wait = max(last[k] + gap, last["q"] + 2.2) - time.time()
    if wait > 0: time.sleep(wait)
    try: return http(LP + "?" + urllib.parse.urlencode({**params, "format": "json"}))
    finally: last[k] = last["q"] = time.time()

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def txt(s): return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()

def parse_matches(h):
    """every match popup on a rendered tournament page"""
    out, seen = [], set()
    for pop in re.split(r'<div class="brkts-popup brkts-popup-container brkts-match-info-popup"', h)[1:]:
        ts = re.search(r'data-timestamp="(\d+)"', pop)
        head = pop.split('class="brkts-popup-body"')[0]
        names = re.findall(r'<span class="name"[^>]*><a [^>]*title="([^"]+)"', head)
        sc = re.findall(r'scoreholder-score(?: match-info-header-winner)?">(\d*)<', head)
        if not ts or len(names) < 2: continue
        bo = re.search(r"\(Bo(\d)\)", head)
        key = (ts[1], names[0], names[1])
        if key in seen: continue
        seen.add(key)
        maps = []
        for row in re.split(r'<div class="brkts-popup-body-grid-row">', pop)[1:]:
            mp = re.search(r'<div class="brkts-popup-spaced"><a [^>]*title="([^"]+)"', row)
            sides = re.split(r'brkts-popup-body-detailed-scores-container', row)
            if not mp or len(sides) < 3: continue
            scores = []
            for part in sides[1:3]:
                main = re.search(r'main-score">([^<]*)<', part)
                halves = re.findall(r'score-color-(atk|def)">(\d*)<', part)
                scores.append([main[1] if main else "", [[s[0][0], int(s[1])] for s in halves if s[1]]])
            agents = [re.findall(r'<img alt="([^"]+)"', sides[0].split("brkts-popup-spaced")[-1]),
                      re.findall(r'<img alt="([^"]+)"', sides[1].split('brkts-popup-spaced"><a')[-1].split("brkts-popup-spaced")[-1])]
            try: s1, s2 = int(scores[0][0]), int(scores[1][0])
            except ValueError: continue  # map not played
            maps.append(dict(map=mp[1], s=[s1, s2], h=[scores[0][1], scores[1][1]], ag=[a[:5] for a in agents]))
        win = 0 if "match-info-header-opponent-left match-info-header-winner" in head else 1 if re.search(r'match-info-header-opponent match-info-header-winner', head) else None
        try: s = [int(sc[0]), int(sc[1])]
        except (ValueError, IndexError):  # no series score shown: count map wins
            s = [sum(m["s"][0] > m["s"][1] for m in maps), sum(m["s"][1] > m["s"][0] for m in maps)] if maps else None
        if not maps and not s: continue
        out.append(dict(ts=int(ts[1]), t=[names[0], names[1]], s=s, bo=int(bo[1]) if bo else None, w=win, maps=maps))
    return sorted(out, key=lambda m: m["ts"])

def parse_stats(h):
    rows, seen = [], set()
    for tr in re.findall(r'<tr class="table2&#95;&#95;row--body">(.*?)</tr>', h, re.S):
        td = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(td) < 17: continue
        pl = re.search(r'<span class="name"[^>]*><a href="/valorant/([^"]+)" title="([^"]+)">([^<]+)</a>', td[1])
        if not pl or pl[1] in seen: continue  # the table repeats per stage; the first is the whole event
        seen.add(pl[1])
        cc = re.search(r'<span class="flag"><img alt="([^"]+)"', td[1])
        team = re.search(r'data-sort-value="([^"]+)"', tr.split("<td")[3]) if tr.count("<td") > 3 else None
        num = lambda x: float(txt(x).rstrip("%") or 0)
        fk, fd = (int(v) for v in txt(td[12]).split("/")[:2]) if "/" in txt(td[12]) else (0, 0)
        rows.append(dict(id=urllib.parse.unquote(pl[1]), n=html.unescape(pl[3]), cc=cc[1] if cc else "", tm=html.unescape(team[1]) if team else "",
                         ag=re.findall(r'title="([^"]+)"', td[3]), m=int(num(td[4])), acs=num(td[5]), adr=num(td[6]), k=int(num(td[7])),
                         d=int(num(td[8])), a=int(num(td[9])), fk=fk, fd=fd, kast=num(td[13])))
    return rows

def riot():
    """team logos by name, and per-match VOD links (YouTube) for the leagues we cover"""
    H = {"x-api-key": KEY}
    p = D / "riot.json"
    cache = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"teams": {}, "matches": {}}
    lgs = http(RIOT + "getLeagues?hl=en-US&sport=val", H)["data"]["leagues"]
    cache["leagues"] = {l["slug"]: [l["name"], l["image"]] for l in lgs}
    want = [l["id"] for l in lgs if l["slug"] in ("champions", "vct_masters", "vct_americas", "vct_emea", "vct_pacific", "vct_china", "emeaclash")]
    page, older = 0, None
    while page < 40:
        q = "getSchedule?hl=en-US&sport=val&leagueId=" + ",".join(want) + (f"&pageToken={older}" if older else "")
        s = http(RIOT + q, H)["data"]["schedule"]
        for ev in s["events"]:
            if ev.get("type") != "match" or not ev.get("match"): continue
            for t in ev["match"]["teams"]:
                if t.get("image"): cache["teams"][t["name"]] = [t.get("code"), t["image"]]
            m = ev["match"]
            if ev["state"] == "completed" and m["id"] not in cache["matches"]:
                cache["matches"][m["id"]] = dict(d=ev["startTime"][:10], lg=ev["league"]["slug"], t=[t["name"] for t in m["teams"]], v=None)
        older = s["pages"].get("older"); page += 1
        if not older or min((e["startTime"] for e in s["events"]), default="9") < "2026-01-01": break
    for mid, m in cache["matches"].items():  # VODs: one call per new completed match
        if m.get("v") is not None or m["d"] < "2026-01-01": continue
        try: ev = http(RIOT + f"getEventDetails?hl=en-US&id={mid}", H)["data"]["event"]
        except Exception: continue
        m["v"] = [next((v["parameter"] + "|" + str(v.get("startMillis") or 0) for v in g.get("vods") or [] if v["provider"] == "youtube" and v["locale"].startswith("en")),
                       next((v["parameter"] + "|" + str(v.get("startMillis") or 0) for v in g.get("vods") or [] if v["provider"] == "youtube"), "")) for g in ev["match"]["games"] if g["state"] == "completed"]
    p.write_text(json.dumps(cache, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"riot: {len(cache['teams'])} team logos, {sum(1 for m in cache['matches'].values() if m.get('v'))} matches with VODs")

def const():
    p = D / "const.json"
    if p.exists() and time.time() - p.stat().st_mtime < 7 * 86400: return
    ag = http("https://valorant-api.com/v1/agents?isPlayableCharacter=true")["data"]
    mp = http("https://valorant-api.com/v1/maps")["data"]
    out = dict(agents={a["displayName"]: dict(icon=a["displayIcon"], art=a.get("fullPortraitV2") or a.get("fullPortrait"), role=(a.get("role") or {}).get("displayName"),
                                              bg=a.get("background"), col=(a.get("backgroundGradientColors") or [None])[0]) for a in ag},
               maps={m["displayName"]: dict(splash=m.get("splash"), icon=m.get("listViewIcon")) for m in mp if m.get("splash")})
    p.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--minutes", type=float, default=30); a = ap.parse_args()
    stop = time.time() + a.minutes * 60
    for d in ("m", "s"): (D / d).mkdir(parents=True, exist_ok=True)
    const()
    try: riot()
    except Exception as e: print("riot failed:", e, file=sys.stderr)
    titles = [p["title"] for p in lp(dict(action="query", list="allpages", apprefix="VCT/2026/", aplimit=500))["query"]["allpages"]]
    tours = [t for t in titles if TOUR_RE.match(t)]
    pages = {t: [t] + [x for x in titles if x == t + "/Group Stage"] for t in tours}
    want = [x for t in tours for x in pages[t] + ([t + "/Statistics"] if t + "/Statistics" in titles else [])]
    revs = {}
    for i in range(0, len(want), 50):
        q = lp(dict(action="query", prop="info", titles="|".join(want[i:i + 50])))
        revs.update({p["title"]: p.get("lastrevid") for p in q["query"]["pages"].values()})
    rp = D / "revs.json"
    seen = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    meta = {}
    for t in tours:
        changed = [x for x in pages[t] + [t + "/Statistics"] if x in revs and seen.get(x) != revs[x]]
        mf, sf = D / "m" / f"{slug(t)}.json", D / "s" / f"{slug(t)}.json"
        if changed and time.time() < stop:
            ms, info = [], {}
            for x in pages[t]:
                h = lp(dict(action="parse", page=x, prop="text"), parse=True)["parse"]["text"]["*"]
                ms += parse_matches(h)
                if x == t:
                    for k in ("Dates", "Start Date", "End Date", "Prize Pool", "Location", "Venue"):
                        v = re.search(rf'<div class="infobox-cell-2 infobox-description">{k}:</div><div[^>]*>(.*?)</div>', h, re.S)
                        if v: info[k] = txt(v[1])
            uniq = {}
            for m in ms: uniq[(m["ts"], *m["t"])] = m
            mf.write_text(json.dumps(dict(title=t, info=info, matches=sorted(uniq.values(), key=lambda m: m["ts"])), separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
            if t + "/Statistics" in revs:
                h = lp(dict(action="parse", page=t + "/Statistics", prop="text"), parse=True)["parse"]["text"]["*"]
                sf.write_text(json.dumps(parse_stats(h), separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
            for x in changed: seen[x] = revs[x]
            rp.write_text(json.dumps(seen, indent=0), encoding="utf-8")
            print(f"{t}: {len(uniq)} matches, {sum(len(m['maps']) for m in uniq.values())} maps", flush=True)
    print(f"valorant: {len(tours)} tournaments, {sum(1 for t in tours if (D / 'm' / f'{slug(t)}.json').exists())} fetched")

if __name__ == "__main__":
    main()
