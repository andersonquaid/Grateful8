"""League edition: Standings, Draft Order and Record Books only, for sharing with the league.
Reads league_data.json (from build_league.py) and writes grateful8_league.html from league_template.html.
Only league-level data goes into the page: no rosters, player values, projections-based odds or lineup advice."""
import json, os, shutil, sys

L = json.load(open("league_data.json"))
cur = L["meta"]["current_season"]
SCRATCH = "/tmp/claude-0/-home-claude/dcd9dc87-bde1-5712-b90f-c1029db5b985/scratchpad/grateful8_league.html"

STAND_KEYS = ("rid", "w", "l", "t", "pf", "pa", "maxpf", "apw", "apn", "weeks", "rank", "ap_pct", "eff",
              "final_place", "exp_wins", "exp_pf")


def if_ended_today(S):
    """Draft order if the regular season ended now.
    Picks 1-4: teams ranked 5-8, lowest Max PF first. Picks 5-8: ranks 4..1 (rank 1 assumed champion, picks 8th).
    2.09 Toilet Bowl winner is TBD. 3.09 goes to the current points-against leader."""
    st = sorted(S["standings"], key=lambda x: x["rank"])
    owner = {(b["round"], b["orig"]): b["owner"] for b in S["draft"]["board"] if not b.get("comp")}
    bottom = sorted(st[4:], key=lambda x: (x["maxpf"], -x["rank"]))
    order = [x["rid"] for x in bottom] + [x["rid"] for x in reversed(st[:4])]
    lba = max(st, key=lambda x: x["pa"])
    board = []
    for r in range(1, S["draft"]["rounds"] + 1):
        for k, rid in enumerate(order, 1):
            board.append({"round": r, "slot": k, "orig": rid, "owner": owner[(r, rid)]})
        if r == 2:
            board.append({"round": 2, "slot": 9, "comp": "cons", "orig": None, "owner": None})
        if r == 3:
            board.append({"round": 3, "slot": 9, "comp": "lba", "orig": lba["rid"], "owner": lba["rid"], "pa": lba["pa"]})
    return board


SL = {lg["league"]["season"]: lg for lg in json.load(open("sleeper.json"))["leagues"]}


def brackets(s, S):
    """Playoff and toilet bowl brackets. In season: seeded from current standings. Complete: Sleeper results with scores.
    Toilet bowl: round-1 losers advance; the loser of the toilet bowl final takes the bowl (pick 2.09).
    Round-1 winners play for 5th."""
    seed = {x["rid"]: x["rank"] for x in S["standings"]}
    by_seed = {x["rank"]: x["rid"] for x in S["standings"]}
    wk1, wk2 = S["playoff_weeks"][:2]
    pts = {}
    for wk in S["weeks"]:
        for r in wk["rows"]:
            pts[(r["w"], r["rid"])] = r["pts"]

    def team(rid, wk):
        return {"rid": rid, "seed": seed[rid], "pts": pts.get((wk, rid))} if rid else None

    def game(gid, label, rnd, a, b, src=None):
        wk = wk1 if rnd == 1 else wk2
        t = sorted([x for x in (a, b) if x], key=lambda r: seed[r])
        g = {"id": gid, "label": label, "round": rnd, "week": wk, "teams": [team(r, wk) for r in t]}
        if src:
            g["src"] = src
        sc = [x["pts"] for x in g["teams"]]
        if len(t) == 2 and None not in sc and S["status"] == "complete":
            g["win"] = t[0] if sc[0] > sc[1] else t[1]
        return g

    live = S["status"] != "complete"
    if live:
        P = [game("sf1", "Semifinal", 1, by_seed[1], by_seed[4]), game("sf2", "Semifinal", 1, by_seed[2], by_seed[3]),
             game("final", "Championship", 2, None, None, ["Winner 1 v 4", "Winner 2 v 3"]),
             game("third", "3rd place", 2, None, None, ["Loser 1 v 4", "Loser 2 v 3"])]
        Tb = [game("t1", "Round 1", 1, by_seed[5], by_seed[8]), game("t2", "Round 1", 1, by_seed[6], by_seed[7]),
              game("tfinal", "Toilet Bowl final", 2, None, None, ["Loser 5 v 8", "Loser 6 v 7"]),
              game("fifth", "5th place", 2, None, None, ["Winner 5 v 8", "Winner 6 v 7"])]
        return {"live": True, "weeks": [wk1, wk2], "playoff": P, "toilet": Tb}
    lg = SL[s]
    wb = {g["m"]: g for g in lg["winners_bracket"]}
    lb = {g["m"]: g for g in lg["losers_bracket"]}
    fin = next(g for g in wb.values() if g.get("p") == 1); thd = next(g for g in wb.values() if g.get("p") == 3)
    r1w = sorted([g for g in wb.values() if g["r"] == 1], key=lambda g: min(seed[g["t1"]], seed[g["t2"]]))
    tfin = next(g for g in lb.values() if g.get("p") == 1); fif = next(g for g in lb.values() if g.get("p") == 3)
    r1l = sorted([g for g in lb.values() if g["r"] == 1], key=lambda g: min(seed[g["t1"]], seed[g["t2"]]))
    P = [game("sf1", "Semifinal", 1, r1w[0]["t1"], r1w[0]["t2"]), game("sf2", "Semifinal", 1, r1w[1]["t1"], r1w[1]["t2"]),
         game("final", "Championship", 2, fin["t1"], fin["t2"]), game("third", "3rd place", 2, thd["t1"], thd["t2"])]
    Tb = [game("t1", "Round 1", 1, r1l[0]["t1"], r1l[0]["t2"]), game("t2", "Round 1", 1, r1l[1]["t1"], r1l[1]["t2"]),
          game("tfinal", "Toilet Bowl final", 2, tfin["t1"], tfin["t2"]), game("fifth", "5th place", 2, fif["t1"], fif["t2"])]
    return {"live": False, "weeks": [wk1, wk2], "playoff": P, "toilet": Tb,
            "champ": fin["w"], "bowl": tfin["w"]}


seasons = {}
for s, S in L["seasons"].items():
    D = S["draft"]
    board = if_ended_today(S) if s == cur else [
        {k: b[k] for k in ("round", "slot", "orig", "owner", "comp") if k in b} for b in D["board"]]
    seasons[s] = {
        "status": S["status"], "reg_weeks": S["reg_weeks"], "last_scored": S["last_scored"],
        "teams": [{k: t[k] for k in ("rid", "owner_id", "owner", "team")} for t in S["teams"]],
        "standings": [{k: x[k] for k in STAND_KEYS if k in x} for x in S["standings"]],
        "records": S["records"],
        "draft": {"season": D["season"], "rounds": D["rounds"], "board": board},
        "brackets": brackets(s, S),
    }

# League Admin tab: static rulebook content plus live payout tracking for the rulebook's season
ADMIN = json.load(open("league_admin.json")) if os.path.exists("league_admin.json") else None
admin_live = None
if ADMIN and ADMIN["season"] in L["seasons"]:
    S = L["seasons"][ADMIN["season"]]
    weekly = []
    for wk in S["weeks"]:
        if wk["w"] <= min(S["reg_weeks"], S["last_scored"]):
            rows = [r for r in wk["rows"] if r.get("pts")]
            if rows:
                hi = max(r["pts"] for r in rows)
                weekly.append({"w": wk["w"], "rids": [r["rid"] for r in rows if r["pts"] == hi], "pts": hi})
    lead = max(S["standings"], key=lambda x: x["pf"])
    admin_live = {"weekly": weekly, "reg_weeks": S["reg_weeks"], "last_scored": S["last_scored"], "status": S["status"],
                  "pf_leader": {"rid": lead["rid"], "pf": lead["pf"]},
                  "places": {str(x["final_place"]): x["rid"] for x in S["standings"] if x.get("final_place")}}

meta = {k: L["meta"][k] for k in ("pulled_at", "current_season", "current_week", "league_name", "scoring")}
data = {"meta": meta, "seasons": seasons, "alltime": L["alltime"], "owners": L["owners"], "admin": ADMIN, "admin_live": admin_live}
txt = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
html = open("league_template.html").read().replace("/*__LEAGUE_DATA__*/", txt)
STANDALONE_HEAD = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    '<meta name="robots" content="noindex,nofollow">'
    '<meta name="description" content="GRateful 8 standings, brackets, draft order and record books.">'
    '<meta property="og:title" content="GRateful 8 League Hub">'
    '<meta property="og:description" content="Standings, brackets, draft order and record books, refreshed weekly from Sleeper.">'
    '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E'
    '%3Crect width=%2232%22 height=%2232%22 rx=%227%22 fill=%22%232447c4%22/%3E%3Ctext x=%2216%22 y=%2223%22 font-family=%22Arial%22 '
    'font-weight=%22700%22 font-size=%2220%22 text-anchor=%22middle%22 fill=%22white%22%3E8%3C/text%3E%3C/svg%3E">'
    '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
    'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style></head><body>'
)
# --standalone PATH: a complete web page (for GitHub Pages); default: the artifact body for claude.ai
if "--standalone" in sys.argv:
    out = sys.argv[sys.argv.index("--standalone") + 1]
    open(out, "w").write(STANDALONE_HEAD + html + "</body></html>")
    print("wrote", out)
else:
    open("grateful8_league.html", "w").write(html)
    if os.path.isdir(os.path.dirname(SCRATCH)):
        shutil.copy("grateful8_league.html", SCRATCH)
print("league data KB", len(txt) // 1024, "page KB", len(html) // 1024)
