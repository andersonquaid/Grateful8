"""Shared helpers for the GRateful 8 league app data build."""
import json

SLOTS_ELIG = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "REC_FLEX": {"WR", "TE"},
    "WRRB_FLEX": {"WR", "RB"},
}


def load_sleeper(path="sleeper.json"):
    return json.load(open(path))


def league_points(stats, pos, sc):
    """Score a Sleeper stat line with league scoring settings (TE premium on receptions)."""
    pts = 0.0
    for k, v in stats.items():
        if k in sc and isinstance(v, (int, float)) and not k.startswith("bonus_rec_"):
            pts += sc[k] * v
    if pos == "TE" and "bonus_rec_te" in sc:
        pts += sc["bonus_rec_te"] * stats.get("rec", 0)
    if pos == "RB" and "bonus_rec_rb" in sc:
        pts += sc["bonus_rec_rb"] * stats.get("rec", 0)
    if pos == "WR" and "bonus_rec_wr" in sc:
        pts += sc["bonus_rec_wr"] * stats.get("rec", 0)
    return round(pts, 2)


def optimal_lineup(cands, slots):
    """cands: list of (player_id, position or set of positions, points). slots: starting slot names.
    Greedy fill of fixed slots first, then flex slots from most to least restrictive.
    Exact for nested eligibility sets like QB/RB/WR/TE -> FLEX -> SUPER_FLEX."""
    pool = sorted(cands, key=lambda c: -c[2])
    used = set()
    lineup = []
    order = sorted(slots, key=lambda s: len(SLOTS_ELIG[s]))
    for s in order:
        elig = SLOTS_ELIG[s]
        for c in pool:
            pos = c[1] if isinstance(c[1], (set, frozenset, list, tuple)) else {c[1]}
            if c[0] not in used and elig & set(pos):
                used.add(c[0])
                lineup.append((s, c))
                break
        else:
            lineup.append((s, None))
    total = round(sum(c[2] for _, c in lineup if c), 2)
    return total, lineup
