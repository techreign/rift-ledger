"""Scrape every pro game of a season from gol.gg into data/games/<tournament>.json (incremental).

  python pipeline/scrape.py                 # all 2026 tournaments, only what's new
  python pipeline/scrape.py --only "LCK 2026"   # tournaments whose name starts with this
  python pipeline/scrape.py --limit 20      # stop after 20 new games (testing)

Per game we read two pages: page-game (teams, objectives, bans, picks, runes, spells, items, KDA, CS) and
page-fullstats (60+ per-player stats). Raw pages (scripts stripped) are kept gzipped in cache/ so the parser can be
re-run without hitting gol.gg again: python pipeline/scrape.py --reparse
"""
import argparse, gzip, html as H, json, re, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, CACHE = ROOT / "data" / "games", ROOT / "cache"
SEASON = "S16"  # gol.gg's name for 2026
BASE = "https://gol.gg"
UA = {"User-Agent": "RiftLedger/0.1 (pro play stats fan site; +https://techreign.github.io/rift-ledger/)"}
RATE = 1.0  # requests per second, across all workers (1.5 got us throttled after ~4 hours)
# Tournaments scraped first, so the site is useful early on a cold start.
PRIORITY = re.compile(r"Worlds|MSI|First Stand|LCK|LPL|LEC|LTA|LCS|LCP|CBLOL|Esports World Cup|EWC")

class Unreachable(Exception): pass
_lock, _next, _fails = threading.Lock(), [0.0], [0]
def fetch(url, data=None):
    """Rate-limited GET/POST. After 3 URLs in a row fail outright, assume we're blocked and stop the whole run."""
    if _fails[0] >= 3: raise Unreachable("gol.gg stopped responding; stopping instead of retrying")
    for attempt in range(4):
        with _lock:
            wait = _next[0] - time.time()
            _next[0] = max(time.time(), _next[0]) + 1 / RATE
        if wait > 0: time.sleep(wait)
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            out = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
            _fails[0] = 0
            return out
        except Exception as e:
            if attempt == 3:
                with _lock: _fails[0] += 1
                raise
            print(f"  retry {url}: {e}", file=sys.stderr); time.sleep(5 * (attempt + 1))

def clean(h): return re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", h, flags=re.S)
def text(h): return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", h))).replace("\xa0", " ").strip()
def num(s):
    s = (s or "").replace("%", "").replace(",", "").strip()
    if s == "Perfect KDA": return None
    try: v = float(s); return int(v) if v.is_integer() else v
    except ValueError: return None
def slug(name): return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def page(gid, kind):
    """Fetch (or read from cache) one game page, scripts stripped."""
    p = CACHE / f"{gid}-{kind}.html.gz"
    if p.exists(): return gzip.decompress(p.read_bytes()).decode()
    h = clean(fetch(f"{BASE}/game/stats/{gid}/page-{kind}/"))
    p.write_bytes(gzip.compress(h.encode(), 6))
    return h

# ---------------------------------------------------------------- parsing
def parse_team(block):
    m = re.search(r"team-stats/(\d+)/[^']*' title='[^']*'>([^<]+)</a>\s*-\s*(WIN|LOSS)", block)
    if not m: return None
    t = dict(id=int(m.group(1)), name=H.unescape(m.group(2)).strip(), win=m.group(3) == "WIN")
    score = lambda alt: num((re.search(rf"alt='{alt}'/>\s*([\d.]+k?)", block) or [None, ""])[1].replace("k", ""))
    t["k"], t["tw"], t["bn"], t["dr"] = score("Kills"), score("Towers"), score("Nashor"), score("Dragons")
    gold = re.search(r"alt='Team Gold'/>\s*([\d.]+)k", block); t["gold"] = round(float(gold.group(1)) * 1000) if gold else None
    head, _, rest = block.partition("Bans")
    t["obj"] = [a for a in re.findall(r"alt='([^']+)'\s*class='champion_icon_XS'", head)]  # drakes, elder, grubs...
    t["fb"] = "alt='First Blood'" in head
    t["ft"] = "alt='First Tower'" in head
    bans, _, picks = rest.partition("Picks")
    champ = r"champion-stats/(\d+)/[^']*' title='([^']+?) stats'"
    t["bans"] = [n for _, n in re.findall(champ, bans)]
    t["picks"] = [n for _, n in re.findall(champ, picks)]
    t["fp"] = "alt='First Pick'" in picks[:400]
    return t

def parse_players(table):
    out = []
    # rows hold a nested rune-tooltip table, so split on each row's first cell instead of matching <tr>..</tr>
    for row in re.split(r"<tr>\s*<td style='white-space:nowrap'>(?=\s*<a href='\.\./champion)", table)[1:6]:
        pm = re.search(r"player-stats/(\d+)/[^']*' title='[^']*'>([^<]+)</a>", row)
        cm = re.search(r"champion-stats/(\d+)/[^']*' title='([^']+?) stats'><img[^>]*src='\.\./_img/champions_icon/([^']+?)\.png'", row)
        if not pm or not cm: continue
        kda = re.search(r">\s*(\d+)/(\d+)/(\d+)\s*<", row)
        cs = re.findall(r"<td style='text-align:center;?'>\s*(\d+)\s*</td>", row)
        tip = re.search(r"<table class='perkztab'>(.*?)</table>", row, flags=re.S)
        runes = [int(x) for x in re.findall(r"perkstyle/(\d+)\.png", tip.group(1))] if tip else []
        top = [int(x) for x in re.findall(r"perkstyle/(\d+)\.png", row[: row.find("perkztab")])] if tip else []
        out.append(dict(
            pid=int(pm.group(1)), n=H.unescape(pm.group(2)).strip(), cid=int(cm.group(1)), c=H.unescape(cm.group(2)), ck=cm.group(3),
            k=int(kda.group(1)) if kda else None, d=int(kda.group(2)) if kda else None, a=int(kda.group(3)) if kda else None,
            cs=int(cs[-1]) if cs else None,
            ks=top[0] if top else None, sub=top[1] if len(top) > 1 else None,
            ru=runes,  # tooltip order: primary/secondary style, then runes and stat shards
            sp=re.findall(r"img/spell/Summoner(\w+)\.png", row),
            it=[int(x) for x in re.findall(r"alt='Item_(\d+)", row)],
        ))
    return out

# full-stats row label -> short key
STATS = {"Role": "role", "Level": "lvl", "Golds": "gold", "Vision Score": "vs", "Wards placed": "wp", "Wards destroyed": "wk",
    "Control Wards Purchased": "cw", "Total damage to Champion": "dmg", "Physical Damage": "pdmg", "Magic Damage": "mdmg",
    "True Damage": "tdmg", "DMG%": "dmgp", "KP%": "kp", "GOLD%": "goldp", "Solo kills": "solo", "Double kills": "x2", "Triple kills": "x3",
    "Quadra kills": "x4", "Penta kills": "x5", "GD@15": "gd15", "CSD@15": "csd15", "XPD@15": "xpd15", "LVLD@15": "lvld15",
    "Objectives Stolen": "steal", "Damage dealt to turrets": "tdmgT", "Total heal": "heal", "Total Heals On Teammates": "healT",
    "Damage self mitigated": "mit", "Total Damage Shielded On Teammates": "shieldT", "Time ccing others": "cc",
    "Total damage taken": "taken", "Total Time Spent Dead": "dead", "CS in Team's Jungle": "csJ", "CS in Enemy Jungle": "csEJ",
    "Shutdown bounty collected": "shutG", "Shutdown bounty lost": "shutL"}

def parse_fullstats(h):
    rows = re.findall(r"<tr>(.*?)</tr>", h, flags=re.S)
    cols = []
    for r in rows:
        champs = re.findall(r"champions_icon/([^']+?)\.png", r)
        if len(champs) == 10: cols = champs; break
    stats = [dict() for _ in range(10)]
    for r in rows:
        cells = [text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
        if len(cells) == 11 and cells[0] in STATS:
            key = STATS[cells[0]]
            for i, v in enumerate(cells[1:]): stats[i][key] = v.lower() if key == "role" else num(v)
    return cols, stats

def parse_game(gid, g, fs):
    title = text((re.search(r"<title>(.*?)</title>", g, flags=re.S) or [None, ""])[1])
    meta = re.search(r"\((\w+)\)\s*-\s*([^<]*?)\s*(\d{4}-\d{2}-\d{2})\s*\(([^)]*)\)", text(g))
    dur = re.search(r"Game Time<br/>\s*<h1>(\d+):(\d+)</h1>", g)
    patch = re.search(r"text-right\">\s*v([\d.]+)", g)
    blue = g.find("blue-line-header"); red = g.find("red-line-header", blue)
    at = [m.start() for m in re.finditer("<table class='playersInfosLine", g)]
    tables = [g[at[0]:at[1]], g[at[1]:]] if len(at) >= 2 else []
    teams = [parse_team(g[blue:red]), parse_team(g[red:g.find("playersInfosLine")])]
    if not dur or None in teams or len(tables) < 2: return None  # not played yet / no data
    players = parse_players(tables[0]) + parse_players(tables[1])
    cols, stats = parse_fullstats(fs) if fs else ([], [])
    for i, p in enumerate(players):
        p["side"] = 0 if i < 5 else 1
        if i < len(cols) and cols[i] == p["ck"]: p["st"] = stats[i]; p["role"] = stats[i].pop("role", None)
    roles = ["top", "jungle", "mid", "adc", "support"]
    for i, p in enumerate(players):
        if not p.get("role"): p["role"] = roles[i % 5]
    return dict(id=gid, title=title.replace(" - Games of Legends", ""), region=meta.group(1) if meta else None,
        fmt=meta.group(2).strip(" -") if meta else None, date=meta.group(3) if meta else None, stage=meta.group(4) if meta else None,
        patch=patch.group(1) if patch else None, len=int(dur.group(1)) * 60 + int(dur.group(2)), teams=teams, players=players)

# ---------------------------------------------------------------- crawl
def matchlist(tr):
    h = clean(fetch(f"{BASE}/tournament/tournament-matchlist/{urllib.parse.quote(tr)}/"))
    out = []
    for r in re.findall(r"<tr>(.*?)</tr>", h, flags=re.S):
        m = re.search(r"game/stats/(\d+)/page-(\w+)/", r)
        if not m or m.group(2) == "preview": continue
        cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.S)]
        out.append(dict(first=int(m.group(1)), a=cells[1], score=cells[2], b=cells[3], stage=cells[4], date=cells[6]))
    return out

def series_ids(g):
    ids = [int(i) for i, n in re.findall(r"href='\.\./game/stats/(\d+)/page-game/'[^>]*>Game (\d+)<", g)]
    return list(dict.fromkeys(ids))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only"); ap.add_argument("--limit", type=int); ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True); CACHE.mkdir(exist_ok=True)
    trs = json.loads(fetch(f"{BASE}/tournament/ajax.trlist.php", data=f"season={SEASON}&league=".encode()))
    trs = [t for t in trs if int(t.get("nbgames") or 0) > 0 and (not args.only or t["trname"].startswith(args.only))]
    trs.sort(key=lambda t: (not PRIORITY.search(t["trname"]), t["lastgame"]), reverse=False)
    (ROOT / "data" / "tournaments.json").write_text(json.dumps(trs, indent=0))
    recent = (date.today() - timedelta(days=10)).isoformat()
    new = 0
    for tr in trs:
        path = DATA / f"{slug(tr['trname'])}.json"
        doc = json.loads(path.read_text()) if path.exists() else dict(name=tr["trname"], region=tr["region"], matches=[], games={})
        have = len(doc["games"])
        if args.reparse:
            for gid in list(doc["games"]):
                g = parse_game(int(gid), page(gid, "game"), page(gid, "fullstats"))
                if g: doc["games"][gid] = g
            path.write_text(json.dumps(doc, separators=(",", ":"))); continue
        if have >= int(tr["nbgames"]) and tr["lastgame"] < recent: continue  # complete and finished
        doc["matches"] = matchlist(tr["trname"])
        todo, bad = [], doc.setdefault("bad", {})  # bad: game id -> failed parses; give up after 2
        done = lambda i: str(i) in doc["games"] or bad.get(str(i), 0) >= 2
        for m in doc["matches"]:
            if m.get("ids") and all(done(i) for i in m["ids"]): continue
            g = page(m["first"], "game"); m["ids"] = series_ids(g) or [m["first"]]
            todo += [i for i in m["ids"] if not done(i)]
        # keep known series ids across runs
        old = {m["first"]: m.get("ids") for m in json.loads(path.read_text())["matches"]} if path.exists() else {}
        for m in doc["matches"]: m["ids"] = m.get("ids") or old.get(m["first"]) or [m["first"]]
        if args.limit: todo = todo[: max(0, args.limit - new)]
        def one(gid):
            try:
                g = parse_game(gid, page(gid, "game"), page(gid, "fullstats"))
                return gid, g
            except Exception as e:
                print(f"  game {gid} failed: {e}", file=sys.stderr); return gid, None
        with ThreadPoolExecutor(args.workers) as ex:
            for gid, g in ex.map(one, todo):
                if g: doc["games"][str(gid)] = g; new += 1; bad.pop(str(gid), None)
                else: bad[str(gid)] = bad.get(str(gid), 0) + 1
        path.write_text(json.dumps(doc, separators=(",", ":")))
        if _fails[0] >= 3: print("gol.gg unreachable, stopping; progress is saved", flush=True); break
        print(f"{tr['trname']}: {len(doc['games'])}/{tr['nbgames']} games (+{len(doc['games']) - have})", flush=True)
        if args.limit and new >= args.limit: break
    print(f"done, {new} new games")

if __name__ == "__main__":
    main()
