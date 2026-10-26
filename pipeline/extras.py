"""Per-game extras from gol.gg into data/extra/<tournament>/<game>.json (incremental, time-boxed; one small file per
game so the bot's commits only ever add files instead of rewriting big ones).

  python pipeline/extras.py --minutes 120     # work through games that lack extras, majors + newest first
  python pipeline/extras.py --reparse         # re-run the parsers over cached raw responses only

Per game: page-timeline (gold per player per minute + event log: kills, plates, towers, objectives) and, for each of
the ten players, game/ajax.build.php (item purchase order, skill order, full rune page with stat shards).
That's 11 requests a game, so a full season takes many hours at the polite rate: the GitHub Action chips away at it
with a time budget each run. Raw responses are cached gzipped in cache/ like scrape.py does.
"""
import argparse, gzip, html as H, json, re, sys, time
from pathlib import Path
from scrape import BASE, CACHE, DATA, PRIORITY, Unreachable, fetch

EXTRA = DATA.parent / "extra"
ROLE = {"TOP": "top", "JGL": "jungle", "MID": "mid", "BOT": "adc", "SPT": "support"}
KEY = {"1": "Q", "2": "W", "3": "E", "4": "R"}

def cached(name, get):
    p = CACHE / name
    if p.exists(): return gzip.decompress(p.read_bytes()).decode()
    s = get(); p.write_bytes(gzip.compress(s.encode(), 6)); return s

def timeline_raw(gid):
    # keep only the gold-graph script; everything else in <script>/<style> is noise
    def get():
        h = fetch(f"{BASE}/game/stats/{gid}/page-timeline/")
        gold = re.search(r"var golddatas\s*=\s*\{.*?\};", h, re.S)
        h = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", h, flags=re.S)
        return (gold.group(0) if gold else "") + "\n" + h
    return cached(f"{gid}-timeline.html.gz", get)

def builds_raw(gid, pids):
    def get():
        out = {}
        for pid in pids:
            out[str(pid)] = json.loads(fetch(f"{BASE}/game/ajax.build.php", data=f"game_id={gid}&player_id={pid}".encode()) or "null")
        return json.dumps(out)
    return json.loads(cached(f"{gid}-builds.json.gz", get))

def parse_timeline(h, players):
    """-> {gold: [10 per-minute arrays in players order], ev: [[sec, side, type, actor, actorChamp, [assists], victimChamp, target]]}"""
    gold = [None] * 10
    m = re.search(r"var golddatas\s*=\s*\{(.*?)\};", h, re.S)
    if m:
        sets = re.findall(r"label:\s*'(\w+)',\s*data:\s*\[([^\]]*)\]\s*,\s*borderColor:\s*'rgba\((\d+),(\d+),(\d+)", m.group(1))
        for label, data, r, g, b in sets:
            side = 0 if int(b) > int(r) else 1
            i = next((i for i, p in enumerate(players) if p["side"] == side and p["role"] == ROLE.get(label)), None)
            if i is not None: gold[i] = [int(float(x)) for x in data.split(",") if x.strip()]
    ev = []
    for row in re.findall(r"<tr onmouseover='ShowPoint\(\d+\)'[^>]*>(.*?)</tr>", h, re.S):
        td = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(td) < 7: continue
        mm = re.match(r"\s*(\d+):(\d+)", td[0])
        if not mm: continue
        champs = re.findall(r"champions_icon/([^'.]+(?:\.[^'.]+)?)\.png", td[3])
        act = re.search(r"_img/([\w-]+)\.png", td[4])
        ev.append([int(mm.group(1)) * 60 + int(mm.group(2)), 0 if "blueside" in td[1] else 1,
                   act.group(1).replace("-icon", "") if act else re.sub(r"<[^>]+>", "", td[4]).strip().lower(),
                   H.unescape(re.sub(r"<[^>]+>", "", td[2]).strip()) or None, champs[0] if champs else None, champs[1:],
                   (re.findall(r"champions_icon/([^']+?)\.png", td[5]) or [None])[0], H.unescape(re.sub(r"<[^>]+>", "", td[6]).strip()) or None])
    return dict(gold=gold, ev=ev)

def parse_build(d):
    """ajax.build.php -> {sk: 'QEWQQRQ...', rn: [primary, sub, p0..p5, s0..s2], bo: [[sec, item], ...]}"""
    if not d or not d[0]: return None
    a = d[0][0]
    sk = "".join(KEY.get(x, "") for x in (a.get("skillorder") or "").split(";") if x)
    rn = [int(a.get(k) or 0) for k in ("perkprimarystyle", "perksubstyle", "perk0", "perk1", "perk2", "perk3", "perk4", "perk5", "statperk0", "statperk1", "statperk2")]
    bo = []
    for e in (d[1] if len(d) > 1 else []):
        t, item = e.get("typeEvent"), int(e.get("itemId") or -1)
        if t == "ITEM_UNDO":
            if bo: bo.pop()
        elif t == "ITEM_PURCHASED" and item > 0:
            bo.append([int(e.get("build_time") or 0), item])
    return dict(sk=sk, rn=rn, bo=bo)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60); ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()
    EXTRA.mkdir(exist_ok=True); CACHE.mkdir(exist_ok=True)
    stop = time.time() + args.minutes * 60
    docs = []
    for f in DATA.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if args.only and not d["name"].startswith(args.only): continue
        last = max((g["date"] or "" for g in d["games"].values()), default="")
        docs.append((not PRIORITY.search(d["name"]), last, f, d))
    docs.sort(key=lambda x: x[1], reverse=True); docs.sort(key=lambda x: x[0])  # majors first, newest first within
    done = 0
    for _, _, f, d in docs:
        out_d = EXTRA / f.stem
        have = {x.stem for x in out_d.glob("*.json")} if out_d.exists() else set()
        gids = sorted(d["games"], key=lambda g: (d["games"][g]["date"] or "", g), reverse=True)
        changed = 0
        for gid in gids:
            if gid in have and not args.reparse: continue
            if args.reparse and not (CACHE / f"{gid}-timeline.html.gz").exists(): continue
            if not args.reparse and time.time() > stop: break
            g = d["games"][gid]
            try:
                tl = parse_timeline(timeline_raw(gid), g["players"])
                b = builds_raw(gid, [p["pid"] for p in g["players"]])
                out_d.mkdir(parents=True, exist_ok=True)
                (out_d / f"{gid}.json").write_text(json.dumps(dict(tl, b={pid: parse_build(v) for pid, v in b.items()}), separators=(",", ":")), encoding="utf-8")
                have.add(gid); changed += 1; done += 1
            except Unreachable as e:
                print(f"  {e}", file=sys.stderr); stop = 0; break
            except Exception as e:
                print(f"  extras {gid} failed: {e}", file=sys.stderr)
        if changed: print(f"{d['name']}: {len(have)}/{len(d['games'])} games with extras (+{changed})", flush=True)
        if not args.reparse and time.time() > stop: break
    print(f"done, {done} games")

if __name__ == "__main__":
    main()
