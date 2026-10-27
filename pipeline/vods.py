"""Official broadcast VODs for pro games, from the lolesports API (the same data lolesports.com shows).

  python pipeline/vods.py [--since 2026-01-01] [--minutes 20]

Walks every league's schedule back to --since, and for each completed match not yet cached asks for its event details:
YouTube video id + start offset per game and locale. Writes data/vods.json:
  {match id: {d: "2026-10-26", lg, teams: [name, name], codes: [..], g: {game number: [youtube id, seconds]}}}
build.py matches these to gol.gg series by date and team names. Matches whose VODs weren't up yet are re-checked for a
week. Time-boxed so the Action can't run long; re-runs continue where it stopped.
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "vods.json"
KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"  # public key the lolesports.com site itself ships
LOCALES = ("en-US", "en-GB", "en-EU")

def api(op, **params):
    url = f"https://esports-api.lolesports.com/persisted/gw/{op}?" + urllib.parse.urlencode({"hl": "en-US", **params})
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"x-api-key": KEY, "User-Agent": "prostats.gg/0.1"})
            return json.load(urllib.request.urlopen(req, timeout=30))["data"]
        except Exception as e:
            if attempt == 2: raise
            time.sleep(2 + 3 * attempt)
    return None

def pick(vods):
    """English broadcast first, otherwise any YouTube VOD: [video id, start seconds]"""
    yt = [v for v in vods if v.get("provider") == "youtube" and v.get("parameter")]
    yt.sort(key=lambda v: LOCALES.index(v.get("locale")) if v.get("locale") in LOCALES else 9)
    return [yt[0]["parameter"], (yt[0].get("startMillis") or 0) // 1000] if yt else None

def _norm(n):
    return "".join(ch for ch in n.lower() if ch.isalnum())

def attach(games):
    """Set g["vod"] = [youtube id, seconds] on gol.gg games (game number from the title) whose lolesports match is the
    same pair of teams within a day. Team names differ between the two (\"Cloud9\" vs \"Cloud9 Kia\"), so a side
    matches on name, prefix, or team code. Returns how many games got one."""
    if not OUT.exists(): return 0
    by_day = {}
    for m in json.loads(OUT.read_text(encoding="utf-8")).values():
        if m["g"]: by_day.setdefault(m["d"], []).append(m)
    def same(a, name, code):
        b = _norm(name)
        return a == b or a == _norm(code) or (len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)))
    n = 0
    for g in games:
        num = re.search(r"(?:^|\s)game\s*(\d+)", g.get("title") or "", re.I)
        if not num or not g.get("date"): continue
        a, b = (_norm(t["name"]) for t in g["teams"])
        d0 = date.fromisoformat(g["date"][:10])
        for day in (d0, d0 - timedelta(days=1), d0 + timedelta(days=1)):
            m = next((m for m in by_day.get(day.isoformat(), ()) if
                      (same(a, m["teams"][0], m["codes"][0]) and same(b, m["teams"][1], m["codes"][1])) or
                      (same(a, m["teams"][1], m["codes"][1]) and same(b, m["teams"][0], m["codes"][0]))), None)
            if m:
                v = m["g"].get(num.group(1))
                if v: g["vod"] = v; n += 1
                break
    return n

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--minutes", type=float, default=20)
    a = ap.parse_args()
    stop = time.time() + a.minutes * 60
    cache = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = []
    for lg in api("getLeagues")["leagues"]:
        token, seen = None, 0
        while time.time() < stop:
            d = api("getSchedule", leagueId=lg["id"], **({"pageToken": token} if token else {}))["schedule"]
            old, known = False, 0
            for e in d["events"]:
                if e.get("type") != "match" or e["state"] != "completed": continue
                day = e["startTime"][:10]
                if day < a.since: old = True; continue
                m = e["match"]; mid = m["id"]
                entry = cache.get(mid)
                fresh = date.fromisoformat(day) >= date.today() - timedelta(days=7)
                if entry and (entry["g"] or (entry.get("chk") and not fresh)): known += 1; continue
                cache[mid] = dict(d=day, t=e["startTime"], lg=lg["name"], teams=[t["name"] for t in m["teams"]], codes=[t["code"] for t in m["teams"]], g=(entry or {}).get("g", {}), **({"chk": 1} if (entry or {}).get("chk") else {}))
                if "hasVod" in (m.get("flags") or []) or fresh: todo.append(mid)
                else: cache[mid]["chk"] = 1  # no VOD flag and settled: nothing to ask for
                seen += 1
            token = d["pages"].get("older")
            # a page of nothing but settled, cached matches: everything older was walked on an earlier run
            if old or not token or (known and known == sum(e.get("type") == "match" and e["state"] == "completed" for e in d["events"])): break
        print(f"{lg['name']}: {seen} new/pending matches", flush=True)
    got = 0
    for i, mid in enumerate(todo):
        if time.time() > stop: print(f"time box hit after {i}/{len(todo)} matches"); break
        try: ev = api("getEventDetails", id=mid)["event"]
        except Exception as e: print("event", mid, e, file=sys.stderr); continue
        g = {str(x["number"]): v for x in ev["match"]["games"] if (v := pick(x.get("vods") or []))}
        cache[mid]["g"] = g; cache[mid]["chk"] = 1; got += bool(g)
        time.sleep(0.25)
        if i % 200 == 199: OUT.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    OUT.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    print(f"{len(cache)} matches cached, {sum(1 for m in cache.values() if m['g'])} with VODs (+{got} this run)")

if __name__ == "__main__":
    main()
