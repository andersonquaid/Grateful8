"""Build league_data.json for the GRateful 8 app: standings, outcome ranges, records,
Monte Carlo odds and draft order.  Run: python3 build_league.py"""
import json, collections, statistics
import numpy as np
from common import load_sleeper, league_points, optimal_lineup

N_SIMS = 20000
RNG = np.random.default_rng(20260930)
MY_USER = "qanderson"

d = load_sleeper()
P = d["players"]
state = d["state"]


def pos_set(pid):
    p = P.get(pid, {})
    return set(p.get("fantasy_positions") or [p.get("position", "?")])


def pname(pid):
    p = P.get(pid, {})
    return p.get("full_name") or (p.get("first_name", "") + " " + p.get("last_name", "")).strip() or pid


def season_slots(L):
    lg = L["league"]
    slots = [s for s in lg["roster_positions"] if s not in ("BN", "IR", "TAXI")]
    nst = len(L["matchups"][0][0]["starters"])
    while len(slots) > nst and "FLEX" in slots:
        slots.remove("FLEX")
    return slots


def fmt_team(u, r):
    meta = (u or {}).get("metadata") or {}
    return {
        "rid": r["roster_id"],
        "owner_id": r["owner_id"],
        "owner": (u or {}).get("display_name", "?"),
        "team": (meta.get("team_name") or (u or {}).get("display_name", "?")).strip(),
        "avatar": (u or {}).get("avatar"),
    }


leagues = sorted(d["leagues"], key=lambda L: L["league"]["season"])
out = {
    "meta": {
        "pulled_at": d["pulled_at"],
        "current_season": state["season"],
        "current_week": state["week"],
        "sims": N_SIMS,
        "league_name": leagues[-1]["league"]["name"],
        "scoring": "Half PPR, TE +0.5 per reception, 4-pt pass TD",
    },
    "seasons": {},
}

all_games = []  # every head-to-head game (regular + postseason)
all_weeks = []  # every team-week with a matchup
worst_perf = collections.defaultdict(list)
best_perf = collections.defaultdict(list)
top_perf = collections.defaultdict(list)
sim_calib_rows = []

for L in leagues:
    lg = L["league"]
    season = lg["season"]
    sc = lg["scoring_settings"]
    slots = season_slots(L)
    reg_end = lg["settings"]["playoff_week_start"] - 1
    complete = lg["status"] == "complete"
    last_scored = 16 if complete else lg["settings"]["last_scored_leg"]
    users = {u["user_id"]: u for u in L["users"]}
    teams = {r["roster_id"]: fmt_team(users.get(r["owner_id"]), r) for r in L["rosters"]}
    proj_by_week = {}
    for w in range(1, 19):
        proj_by_week[w] = {
            x["pid"]: league_points(x["s"], P.get(x["pid"], {}).get("position"), sc)
            for x in d["projections"][season][w - 1]
        }

    weeks = []
    for w in range(1, last_scored + 1):
        ms = [m for m in L["matchups"][w - 1] if m["matchup_id"] is not None]
        if not ms:
            continue
        by_mid = collections.defaultdict(list)
        for m in ms:
            by_mid[m["matchup_id"]].append(m)
        rows = []
        scores = {m["roster_id"]: m["points"] for m in ms}
        for m in ms:
            pp = m["players_points"] or {}
            mx, _ = optimal_lineup([(p, pos_set(p), v) for p, v in pp.items()], slots)
            opp = [x for x in by_mid[m["matchup_id"]] if x["roster_id"] != m["roster_id"]]
            opp = opp[0] if opp else None
            others = [v for k, v in scores.items() if k != m["roster_id"]]
            ap_w = sum(1 for v in others if m["points"] > v) + 0.5 * sum(1 for v in others if m["points"] == v)
            res = None
            if opp:
                res = "W" if m["points"] > opp["points"] else ("L" if m["points"] < opp["points"] else "T")
            row = {
                "w": w, "rid": m["roster_id"], "pts": round(m["points"], 2), "max": mx,
                "opp": opp["roster_id"] if opp else None, "opp_pts": round(opp["points"], 2) if opp else None,
                "res": res, "ap_w": ap_w, "ap_n": len(others), "post": w > reg_end,
            }
            rows.append(row)
            rec = dict(row, season=season, owner_id=teams[m["roster_id"]]["owner_id"])
            all_weeks.append(rec)
            if opp:
                all_games.append(rec)
            # projection calibration + worst performances
            proj = proj_by_week[w]
            po, _ = optimal_lineup([(p, pos_set(p), proj.get(p, 0)) for p in m["players"]], slots)
            sim_calib_rows.append((season, w, m["roster_id"], m["points"], mx, po))
            starters_set = set(m["starters"] or [])
            for pid, act in (m["players_points"] or {}).items():
                if pid != "0":
                    top_perf[season].append({
                        "season": season, "w": w, "rid": m["roster_id"], "opp": opp["roster_id"] if opp else None,
                        "post": w > reg_end, "res": res, "pid": pid, "player": pname(pid), "pos": P.get(pid, {}).get("position"),
                        "act": round(act, 2), "proj": proj.get(pid), "bench": pid not in starters_set,
                    })
            # costliest busts: in a loss, a starter whose shortfall vs projection exceeded the margin
            if opp and m["points"] < opp["points"]:
                margin = round(opp["points"] - m["points"], 2)
                busts = []
                for pid, act in zip(m["starters"], m["starters_points"]):
                    if pid in proj and pid != "0":
                        short = round(proj[pid] - act, 2)
                        if short > margin:
                            busts.append({
                                "season": season, "w": w, "rid": m["roster_id"], "opp": opp["roster_id"], "post": w > reg_end,
                                "pid": pid, "player": pname(pid), "pos": P.get(pid, {}).get("position"),
                                "act": round(act, 2), "proj": proj[pid], "short": short, "margin": margin,
                            })
                if busts:
                    worst_perf[season].append(max(busts, key=lambda b: b["short"]))
            # best game-winning performances: in a win, a starter whose points over projection exceeded the margin
            if opp and m["points"] > opp["points"]:
                margin = round(m["points"] - opp["points"], 2)
                heroes = []
                for pid, act in zip(m["starters"], m["starters_points"]):
                    if pid in proj and pid != "0":
                        over = round(act - proj[pid], 2)
                        if over > margin:
                            heroes.append({
                                "season": season, "w": w, "rid": m["roster_id"], "opp": opp["roster_id"], "post": w > reg_end,
                                "pid": pid, "player": pname(pid), "pos": P.get(pid, {}).get("position"),
                                "act": round(act, 2), "proj": proj[pid], "over": over, "margin": margin,
                            })
                if heroes:
                    best_perf[season].append(max(heroes, key=lambda h_: h_["over"]))
        weeks.append({"w": w, "rows": rows})

    out["seasons"][season] = {
        "status": lg["status"], "reg_weeks": reg_end, "playoff_weeks": [reg_end + 1, reg_end + 2],
        "slots": slots, "teams": teams, "weeks": weeks, "last_scored": last_scored,
        "_L": L, "_proj": proj_by_week, "_sc": sc,
    }

# ---------------- standings ----------------
def standings(S, reg_only=True):
    tab = {}
    for rid, t in S["teams"].items():
        tab[rid] = dict(rid=rid, w=0, l=0, t=0, pf=0.0, pa=0.0, maxpf=0.0, apw=0.0, apn=0, weeks=0)
    for wk in S["weeks"]:
        if reg_only and wk["w"] > S["reg_weeks"]:
            continue
        for r in wk["rows"]:
            x = tab[r["rid"]]
            x["pf"] += r["pts"]; x["maxpf"] += r["max"]; x["apw"] += r["ap_w"]; x["apn"] += r["ap_n"]; x["weeks"] += 1
            if r["opp"] is not None:
                x["pa"] += r["opp_pts"]
                x[{"W": "w", "L": "l", "T": "t"}[r["res"]]] += 1
    order = sorted(tab.values(), key=lambda x: (-(x["w"] + 0.5 * x["t"]), -x["pf"]))
    for i, x in enumerate(order):
        x["rank"] = i + 1
        x["pf"] = round(x["pf"], 2); x["pa"] = round(x["pa"], 2); x["maxpf"] = round(x["maxpf"], 2)
        x["ap_pct"] = round(x["apw"] / x["apn"], 4) if x["apn"] else None
        x["eff"] = round(x["pf"] / x["maxpf"], 4) if x["maxpf"] else None
    return order


def bracket_results(L, S):
    """Final place per roster from actual scores (1-4 playoffs, 5-8 Toilet Bowl), or None if incomplete.
    Toilet Bowl: round-1 winners meet in the final; its winner is 5th and gets pick 2.09. Round-1 losers play for
    last place; the loser is 8th and takes the punishment. Sleeper tracks that bracket losers-advance (for the
    punishment), so its "w" is not the game winner there; scores decide here."""
    start = L["league"]["settings"]["playoff_week_start"]
    pts = {(r["w"], r["rid"]): r["pts"] for wk in S["weeks"] for r in wk["rows"]}

    def result(g):
        a, b, w = g.get("t1"), g.get("t2"), start + g["r"] - 1
        if not a or not b or (w, a) not in pts or (w, b) not in pts:
            return None
        return (a, b) if pts[(w, a)] > pts[(w, b)] else (b, a)

    place = {}
    for g in L["winners_bracket"] or []:
        res = result(g) if g.get("p") in (1, 3) else None
        if res:
            base = 0 if g["p"] == 1 else 2
            place[res[0]], place[res[1]] = base + 1, base + 2
    lb = L["losers_bracket"] or []
    r1_winners = {res[0] for res in (result(g) for g in lb if g["r"] == 1) if res}
    for g in lb:
        res = result(g) if g["r"] == 2 else None
        if res:
            base = 4 if {g["t1"], g["t2"]} <= r1_winners else 6
            place[res[0]], place[res[1]] = base + 1, base + 2
    return place if len(place) == 8 else None


def draft_order(stand, place, cons_winner):
    """1-4: non-playoff teams by lowest max PF; 5-8 by playoff finish (4th->5 ... champ->8)."""
    playoff = [x["rid"] for x in stand[:4]]
    non = sorted([x for x in stand[4:]], key=lambda x: x["maxpf"])
    order = [x["rid"] for x in non]
    order += sorted(playoff, key=lambda rid: -place[rid])  # 4th place first
    lba = max(stand, key=lambda x: x["pa"])["rid"]
    return order, cons_winner, lba


def pick_owner(traded, draft_season, rnd, orig):
    for t in traded:
        if t["season"] == draft_season and t["round"] == rnd and t["roster_id"] == orig:
            return t["owner_id"]
    return orig


# ---------------- Monte Carlo (current season) ----------------
calib = np.array([r[3:] for r in sim_calib_rows])
S_act, M_act, PO = calib.T
K_MAX = M_act.sum() / PO.sum()
SD_MAX = float(np.std(M_act - K_MAX * PO))
EFF = S_act / M_act
EFF_MEAN, EFF_SD = float(EFF.mean()), float(EFF.std())
team_eff = collections.defaultdict(list)
for (season, w, rid, s, m, po) in sim_calib_rows:
    team_eff[rid].append(s / m)
TEAM_EFF = {rid: 0.5 * EFF_MEAN + 0.5 * float(np.mean(v)) for rid, v in team_eff.items()}

cur = out["meta"]["current_season"]
C = out["seasons"][cur]
L = C["_L"]
sc = C["_sc"]
slots = C["slots"]
reg_end = C["reg_weeks"]
first_open = C["last_scored"] + 1
cur_week = state["week"]
rosters = {r["roster_id"]: r for r in L["rosters"]}
OUT_NOW = {"Out", "Doubtful"}
LONG_OUT = {"IR", "PUP", "NFI", "Sus", "COV"}


def avail_factor(pid, w):
    st = P.get(pid, {}).get("injury_status")
    if st in LONG_OUT and w < cur_week + 4:
        return 0.0
    if st == "Out" and w == cur_week:
        return 0.0
    if st == "Doubtful" and w == cur_week:
        return 0.25
    if st == "Questionable" and w == cur_week:
        return 0.85
    return 1.0


proj_mu = {}  # (rid, w) -> projected optimal lineup total, league scoring
proj_lineups = {}
for rid, r in rosters.items():
    active = [p for p in (r["players"] or []) if p not in set(r.get("taxi") or [])]
    for w in range(first_open, reg_end + 3):
        pr = C["_proj"][w]
        cands = [(p, pos_set(p), round(pr.get(p, 0) * avail_factor(p, w), 2)) for p in active]
        tot, lu = optimal_lineup(cands, slots)
        proj_mu[(rid, w)] = tot
        if w == cur_week:
            proj_lineups[rid] = [(s, c[0] if c else None, c[2] if c else 0) for s, c in lu]

sched = {}
for w in range(first_open, reg_end + 1):
    pairs = collections.defaultdict(list)
    for m in L["matchups"][w - 1]:
        pairs[m["matchup_id"]].append(m["roster_id"])
    sched[w] = [tuple(v) for v in pairs.values() if len(v) == 2]

base = {x["rid"]: x for x in standings(C)}
rids = sorted(rosters)
idx = {rid: i for i, rid in enumerate(rids)}
T = len(rids)


def sim_week(w, n):
    mu = np.array([proj_mu[(rid, w)] for rid in rids])
    O = RNG.normal(K_MAX * mu[None, :], SD_MAX, size=(n, T))
    O = np.clip(O, 20, None)
    eff = RNG.normal([TEAM_EFF.get(rid, EFF_MEAN) for rid in rids], EFF_SD, size=(n, T))
    eff = np.clip(eff, 0.5, 1.0)
    return O * eff, O


n = N_SIMS
W = np.tile([base[r]["w"] + 0.5 * base[r]["t"] for r in rids], (n, 1)).astype(float)
PF = np.tile([base[r]["pf"] for r in rids], (n, 1))
PA = np.tile([base[r]["pa"] for r in rids], (n, 1))
MX = np.tile([base[r]["maxpf"] for r in rids], (n, 1))
for w in range(first_open, reg_end + 1):
    Sw, Ow = sim_week(w, n)
    PF += Sw; MX += Ow
    for a, b in sched[w]:
        ia, ib = idx[a], idx[b]
        aw = Sw[:, ia] > Sw[:, ib]
        W[:, ia] += aw; W[:, ib] += ~aw
        PA[:, ia] += Sw[:, ib]; PA[:, ib] += Sw[:, ia]

# seeds: wins then PF
key = W * 1e5 + PF
order = np.argsort(-key, axis=1)  # seed order (indices)
seedrank = np.empty_like(order)
rows_i = np.arange(n)[:, None]
seedrank[rows_i, order] = np.arange(T)[None, :]
S15, _ = sim_week(reg_end + 1, n)
S16, _ = sim_week(reg_end + 2, n)
s1, s2, s3, s4, s5, s6, s7, s8 = [order[:, k] for k in range(8)]
g = lambda S, i: S[np.arange(n), i]
w14 = np.where(g(S15, s1) > g(S15, s4), s1, s4); l14 = np.where(w14 == s1, s4, s1)
w23 = np.where(g(S15, s2) > g(S15, s3), s2, s3); l23 = np.where(w23 == s2, s3, s2)
champ = np.where(g(S16, w14) > g(S16, w23), w14, w23); runner = np.where(champ == w14, w23, w14)
third = np.where(g(S16, l14) > g(S16, l23), l14, l23); fourth = np.where(third == l14, l23, l14)
# Toilet Bowl: round-1 winners meet for pick 2.09 (round-1 losers play for last place and the punishment)
t58 = np.where(g(S15, s5) > g(S15, s8), s5, s8)
t67 = np.where(g(S15, s6) > g(S15, s7), s6, s7)
cons = np.where(g(S16, t58) > g(S16, t67), t58, t67)
# draft slots
slot = np.zeros((n, T), dtype=int)
non = order[:, 4:]
mxn = MX[rows_i, non]
nonorder = np.take_along_axis(non, np.argsort(mxn, axis=1), axis=1)
for k in range(4):
    slot[np.arange(n), nonorder[:, k]] = k + 1
slot[np.arange(n), fourth] = 5; slot[np.arange(n), third] = 6
slot[np.arange(n), runner] = 7; slot[np.arange(n), champ] = 8
lba = np.argmax(PA, axis=1)

odds = {}
for rid in rids:
    i = idx[rid]
    odds[rid] = {
        "playoff": float((seedrank[:, i] < 4).mean()),
        "champ": float((champ == i).mean()),
        "first_pick": float((slot[:, i] == 1).mean()),
        "slot_dist": [float((slot[:, i] == k).mean()) for k in range(1, 9)],
        "cons": float((cons == i).mean()),
        "lba": float((lba == i).mean()),
        "exp_wins": float(W[:, i].mean()),
        "exp_pf": float(PF[:, i].mean()),
        "seed_dist": [float((seedrank[:, i] == k).mean()) for k in range(8)],
    }

# ---------------- assemble per season ----------------
def records_for(weeks_rows, top=10):
    games = [r for r in weeks_rows if r["opp"] is not None]
    def pick(lst, key, rev, keep):
        return [{k: r[k] for k in keep if k in r} for r in sorted(lst, key=key, reverse=rev)[:top]]
    keep = ["season", "w", "rid", "owner_id", "pts", "max", "opp", "opp_pts", "res", "post"]
    for r in weeks_rows:
        r["eff"] = round(r["pts"] / r["max"], 4) if r["max"] else 0
    keep_e = keep + ["eff"]
    return {
        "high": pick(games, lambda r: r["pts"], True, keep),
        "low": pick(games, lambda r: r["pts"], False, keep),
        "lucky": pick([r for r in games if r["res"] == "W"], lambda r: r["pts"], False, keep),
        "unlucky": pick([r for r in games if r["res"] == "L"], lambda r: r["pts"], True, keep),
        "eff": pick(games, lambda r: r["eff"], True, keep_e),
        "ineff": pick(games, lambda r: r["eff"], False, keep_e),
    }


for season, S in out["seasons"].items():
    Lx = S.pop("_L"); S.pop("_proj"); S.pop("_sc")
    stand = standings(S)
    place = bracket_results(Lx, S) if S["status"] == "complete" else None
    for x in stand:
        if season == cur:
            o = odds[x["rid"]]
            x.update(playoff_pct=o["playoff"], champ_pct=o["champ"], first_pick_pct=o["first_pick"],
                     exp_wins=round(o["exp_wins"], 2), exp_pf=round(o["exp_pf"], 1))
        else:
            fin = place[x["rid"]]
            x.update(playoff_pct=1.0 if fin <= 4 else 0.0, champ_pct=1.0 if fin == 1 else 0.0, final_place=fin)
    S["standings"] = stand
    # outcome range: actual regular-season weekly scores
    oc = {}
    for wk in S["weeks"]:
        if wk["w"] > S["reg_weeks"]:
            continue
        for r in wk["rows"]:
            oc.setdefault(r["rid"], []).append(r["pts"])
    S["outcomes"] = oc
    rows = [dict(r, season=season, owner_id=S["teams"][r["rid"]]["owner_id"]) for wk in S["weeks"] for r in wk["rows"]]
    S["records"] = records_for(rows)
    S["records"]["busts"] = sorted(worst_perf[season], key=lambda r: -r["short"])[:10]
    S["records"]["heroes"] = sorted(best_perf[season], key=lambda r: -r["over"])[:10]
    S["records"]["top"] = sorted(top_perf[season], key=lambda r: -r["act"])[:10]
    # draft board for the following year's rookie draft
    draft_season = str(int(season) + 1)
    rounds = Lx["league"]["settings"]["draft_rounds"]
    traded = next(x for x in leagues if x["league"]["season"] == cur)["traded_picks"] if season != cur else Lx["traded_picks"]
    board = []
    if season == cur:
        exp_slot = {rid: sum((k + 1) * p for k, p in enumerate(odds[rid]["slot_dist"])) for rid in rids}
        proj_order = sorted(rids, key=lambda r: exp_slot[r])
        for rnd in range(1, rounds + 1):
            for k, orig in enumerate(proj_order):
                board.append({"round": rnd, "slot": k + 1, "orig": orig, "owner": pick_owner(traded, draft_season, rnd, orig),
                              "prob": odds[orig]["slot_dist"][k], "exp_slot": round(exp_slot[orig], 2),
                              "dist": [round(v, 4) for v in odds[orig]["slot_dist"]]})
            if rnd in (2, 3):
                kind = "cons" if rnd == 2 else "lba"
                dist = sorted(((odds[r][kind], r) for r in rids), reverse=True)
                board.append({"round": rnd, "slot": 9, "comp": kind, "orig": dist[0][1], "owner": dist[0][1],
                              "prob": dist[0][0], "cands": [{"rid": r, "p": round(p, 4)} for p, r in dist if p > 0.0005]})
    else:
        cons_w = next(r for r, p_ in place.items() if p_ == 5)  # Toilet Bowl winner
        order_, consw, lbaw = draft_order(stand, place, cons_w)
        for rnd in range(1, rounds + 1):
            for k, orig in enumerate(order_):
                board.append({"round": rnd, "slot": k + 1, "orig": orig, "owner": pick_owner(traded, draft_season, rnd, orig), "prob": 1.0})
            if rnd in (2, 3):
                w_ = consw if rnd == 2 else lbaw
                board.append({"round": rnd, "slot": 9, "comp": "cons" if rnd == 2 else "lba", "orig": w_, "owner": w_, "prob": 1.0})
    S["draft"] = {"season": draft_season, "rounds": rounds, "board": board}
    S["teams"] = list(S["teams"].values())

# all-time
owners = {}
for S in out["seasons"].values():
    for t in S["teams"]:
        owners[t["owner_id"]] = {"owner": t["owner"], "team": t["team"]}
at = records_for([dict(r) for r in all_weeks])
reg_seasons = []
for season, S in out["seasons"].items():
    for x in S["standings"]:
        reg_seasons.append({"season": season, "rid": x["rid"], "owner_id": S["teams"][[t["rid"] for t in S["teams"]].index(x["rid"])]["owner_id"],
                            "w": x["w"], "l": x["l"], "ap_pct": x["ap_pct"], "complete": S["status"] == "complete"})
agg = collections.defaultdict(lambda: dict(w=0, l=0, t=0, apw=0.0, apn=0, pts=0.0, mx=0.0))
for r in all_weeks:
    a = agg[r["owner_id"]]
    a["apw"] += r["ap_w"]; a["apn"] += r["ap_n"]; a["pts"] += r["pts"]; a["mx"] += r["max"]
    if r["opp"] is not None:
        a[{"W": "w", "L": "l", "T": "t"}[r["res"]]] += 1
at["most_wins_season"] = sorted(reg_seasons, key=lambda x: -x["w"])[:10]
at["most_wins_all"] = sorted([dict(owner_id=k, w=v["w"], l=v["l"], t=v["t"]) for k, v in agg.items()], key=lambda x: -x["w"])[:8]
at["ap_season"] = sorted(reg_seasons, key=lambda x: -x["ap_pct"])[:10]
at["ap_all"] = sorted([dict(owner_id=k, ap_pct=round(v["apw"] / v["apn"], 4), apw=v["apw"], apn=v["apn"]) for k, v in agg.items()], key=lambda x: -x["ap_pct"])[:8]
at["eff_team"] = sorted([dict(owner_id=k, eff=round(v["pts"] / v["mx"], 4), pts=round(v["pts"], 2), mx=round(v["mx"], 2)) for k, v in agg.items()], key=lambda x: -x["eff"])[:8]
out["alltime"] = at
out["owners"] = owners
me = next(t for t in out["seasons"][cur]["teams"] if t["owner"] == MY_USER)
out["meta"]["my_rid"] = me["rid"]
out["meta"]["my_owner_id"] = me["owner_id"]
out["sim"] = {
    "first_week": first_open, "reg_end": reg_end, "k_max": round(K_MAX, 4), "sd_max": round(SD_MAX, 2),
    "eff_mean": round(EFF_MEAN, 4), "eff_sd": round(EFF_SD, 4), "calib_n": len(sim_calib_rows),
    "proj_mu": {f"{rid}-{w}": v for (rid, w), v in proj_mu.items()},
    "odds": {str(k): v for k, v in odds.items()},
}
out["this_week"] = {
    "week": cur_week,
    "lineups": {str(rid): [{"slot": s, "pid": p, "proj": v} for s, p, v in lu] for rid, lu in proj_lineups.items()},
    "matchups": [list(p) for p in sched.get(cur_week, [])],
}
json.dump(out, open("league_data.json", "w"), separators=(",", ":"))
print("wrote league_data.json", len(json.dumps(out)) // 1024, "KB")
print("calibration", out["sim"]["k_max"], out["sim"]["sd_max"], out["sim"]["eff_mean"], out["sim"]["eff_sd"], out["sim"]["calib_n"])
for x in out["seasons"][cur]["standings"]:
    print(x["rank"], x["rid"], f'{x["w"]}-{x["l"]}', x["pf"], x["maxpf"], x["pa"], x["ap_pct"], x["eff"],
          round(x["playoff_pct"], 3), round(x["champ_pct"], 3), round(x["first_pick_pct"], 3), x["exp_wins"])
