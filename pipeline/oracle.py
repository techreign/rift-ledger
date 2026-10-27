"""Convert Oracle's Elixir yearly CSVs into compact per-season files for the lifetime (all seasons) view.

  python pipeline/oracle.py [csv_dir]      # default ~/dev/oracle-data

Writes data/oe/<year>.json.gz (every game before 2026 in the site's game shape, ids still Oracle's) and
data/oe/bridge.json (2026 Oracle ids next to names/teams, so build.py can link a 2026 gol.gg player to their
Oracle history). 2026 games themselves come from gol.gg. Re-run when a missing year's CSV is added; the CSVs
are too big to commit (80-110 MB each), the outputs are not.
"""
import csv, gzip, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "oe"
ROLE = {"top": "top", "jng": "jungle", "mid": "mid", "bot": "adc", "sup": "support"}
# Oracle league codes -> the names the site (and gol.gg) uses
LEAGUE = {"WLDs": "Worlds", "EWC": "Esports World Cup", "FST": "First Stand", "LCKC": "LCK CL", "CK": "LCK CL",
    "NACL": "NA Challengers", "EM": "EMEA Masters", "EUM": "EU Masters", "DCup": "Demacia Cup", "MSC": "Mid-Season Cup",
    "LTA N": "LTA North", "LTA S": "LTA South", "CBLOLA": "CBLOL Academy", "AmCh": "Americas Challengers"}

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def num(x, f=int):
    try: return f(float(x))
    except (TypeError, ValueError): return None
def oid(raw, *fallback):
    """'oe:player:e4e9...' -> 'e4e943fa882'; rows without an id get one from name + team so they still group"""
    if raw: return raw.rsplit(":", 1)[-1][:12]
    return "n" + hashlib.md5("|".join(fallback).lower().encode()).hexdigest()[:11]
def patch(p):
    m = re.match(r"(\d+)\.(\d+)", p or "")
    return f"{int(m[1])}.{int(m[2])}" if m else None

def convert(path, year):
    games, tours = {}, {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            gid = re.sub(r"[^A-Za-z0-9]+", "_", r["gameid"]).strip("_")
            if not gid or r["side"] not in ("Blue", "Red"): continue
            side = 0 if r["side"] == "Blue" else 1
            lg = LEAGUE.get(r["league"], r["league"])
            split = (r["split"] or "").strip()
            po = r["playoffs"] == "1"
            t = "-".join(x for x in (str(year), slug(lg), slug(split), "playoffs" if po else "") if x)
            if t not in tours:
                tours[t] = dict(s=t, n=" ".join(x for x in (lg, str(year), split, "Playoffs" if po else "") if x), lg=lg, y=year)
            g = games.get(gid)
            if g is None:
                g = games[gid] = dict(id=gid, t=t, date=r["date"][:10], gn=num(r["game"]), patch=patch(r["patch"]),
                    len=num(r["gamelength"]) or 0, teams=[None, None], players=[])
            team_id = oid(r["teamid"], r["teamname"])
            if r["position"] == "team":
                g["teams"][side] = dict(oid=team_id, name=r["teamname"], win=r["result"] == "1", k=num(r["kills"]) or 0,
                    tw=num(r["towers"]), dr=num(r["dragons"]), bn=num(r["barons"]), gold=num(r["totalgold"]),
                    bans=[b for b in (r[f"ban{i}"] for i in range(1, 6)) if b])
                continue
            k, d, a, tk = (num(r[c]) or 0 for c in ("kills", "deaths", "assists", "teamkills"))
            st = dict(gold=num(r["totalgold"]), dmg=num(r["damagetochampions"]), vs=num(r["visionscore"]),
                kp=round(100 * (k + a) / tk, 1) if tk else None, gd15=num(r["golddiffat15"]), csd15=num(r["csdiffat15"]),
                xpd15=num(r["xpdiffat15"]), wp=num(r["wardsplaced"]), wk=num(r["wardskilled"]), cw=num(r["controlwardsbought"]),
                dmgp=num(r["damageshare"], lambda v: round(100 * v, 1)), tdmgT=num(r["damagetotowers"]),
                goldp=num(r["earnedgoldshare"], lambda v: round(100 * v, 1)),
                x2=num(r["doublekills"]), x3=num(r["triplekills"]), x4=num(r["quadrakills"]), x5=num(r["pentakills"]),
                fb=1 if r["firstbloodkill"] == "1" else None)
            g["players"].append(dict(oid=oid(r["playerid"], r["playername"], team_id), n=r["playername"], tm=team_id,
                c=r["champion"], role=ROLE.get(r["position"], r["position"]), side=side, k=k, d=d, a=a,
                cs=num(r["total cs"]) if r["total cs"] else (num(r["minionkills"]) or 0) + (num(r["monsterkills"]) or 0),
                st={x: v for x, v in st.items() if v is not None}))
    ok = [g for g in games.values() if all(g["teams"]) and len(g["players"]) == 10 and g["len"]]
    for g in ok: g["players"].sort(key=lambda p: (p["side"], list(ROLE.values()).index(p["role"]) if p["role"] in ROLE.values() else 9))
    used = {g["t"] for g in ok}
    print(f"{year}: {len(ok)} games ({len(games) - len(ok)} incomplete skipped), {len(used)} tournaments")
    return dict(year=year, tours=[t for t in tours.values() if t["s"] in used], games=ok)

def bridge(path):
    """2026 Oracle rows -> [[oracle player id, name, team, role]] and [[oracle team id, team]]"""
    ps, ts = {}, {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["position"] == "team":
                if r["teamid"]: ts[oid(r["teamid"])] = r["teamname"]
            elif r["playerid"]:
                ps[(oid(r["playerid"]), r["playername"], r["teamname"])] = ROLE.get(r["position"], r["position"])
    return dict(players=[[*k, v] for k, v in ps.items()], teams=[[k, v] for k, v in ts.items()])

def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "dev" / "oracle-data")
    OUT.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*_LoL_esports_match_data_from_OraclesElixir.csv")):
        year = int(f.name[:4])
        if year >= 2026:
            (OUT / "bridge.json").write_text(json.dumps(bridge(f), separators=(",", ":")), encoding="utf-8")
            continue
        doc = convert(f, year)
        # mtime=0 keeps the bytes identical across runs, so unchanged years don't show up as modified in git
        (OUT / f"{year}.json.gz").write_bytes(gzip.compress(json.dumps(doc, separators=(",", ":")).encode(), 9, mtime=0))
    for f in sorted(OUT.iterdir()): print(f"  {f.name}: {f.stat().st_size / 1e6:.1f} MB")

if __name__ == "__main__":
    main()
