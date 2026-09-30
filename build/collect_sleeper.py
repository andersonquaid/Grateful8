"""Pull everything the league hub needs from the public Sleeper API into sleeper.json.
Python port of collect_sleeper.js, for GitHub Actions (no browser needed). Run: python collect_sleeper.py"""
import datetime, json, sys, time, urllib.request

A = "https://api.sleeper.app"
KNOWN_LEAGUE = "1336932858421342208"   # GRateful 8, 2026 season
USERNAME = "qanderson"
POS = "position[]=QB&position[]=RB&position[]=WR&position[]=TE"
KEEP = ["full_name", "first_name", "last_name", "position", "fantasy_positions", "team", "age", "birth_date", "years_exp",
        "injury_status", "injury_body_part", "status", "gsis_id", "search_rank", "depth_chart_order", "depth_chart_position",
        "number", "college", "height", "weight", "active", "rookie_year"]


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "grateful8-league-hub"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # network blips: back off and retry
            err = e
            time.sleep(1 + 2 * i)
    print("FAILED", url, err, file=sys.stderr)
    return None


def current_league_id(state):
    """Follow the league into new seasons: find this user's league whose previous_league_id chain reaches KNOWN_LEAGUE."""
    season = state.get("league_season") or state.get("season")
    user = get(f"{A}/v1/user/{USERNAME}")
    if not user or not season:
        return KNOWN_LEAGUE
    for lg in get(f"{A}/v1/user/{user['user_id']}/leagues/nfl/{season}") or []:
        lid, hops = lg["league_id"], 0
        while lid and lid != "0" and hops < 6:
            if lid == KNOWN_LEAGUE:
                return lg["league_id"]
            nxt = get(f"{A}/v1/league/{lid}")
            lid, hops = (nxt or {}).get("previous_league_id"), hops + 1
    return KNOWN_LEAGUE


def slim(arr):
    out = []
    for x in arr or []:
        s = x.get("stats") or {}
        if not (s.get("pts_half_ppr") or s.get("gp")):
            continue
        out.append({"pid": x.get("player_id"), "opp": x.get("opponent"), "team": x.get("team"),
                    "s": {k: v for k, v in s.items() if "adp" not in k and isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0}})
    return out


def main():
    out = {"pulled_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
           "state": get(f"{A}/v1/state/nfl"), "leagues": []}
    if not out["state"]:
        sys.exit("Sleeper state unavailable")
    lid = current_league_id(out["state"])
    while lid and lid != "0":
        lg = get(f"{A}/v1/league/{lid}")
        if not lg:
            sys.exit(f"league {lid} unavailable")
        parts = {p: get(f"{A}/v1/league/{lid}/{p}") for p in ("users", "rosters", "winners_bracket", "losers_bracket", "traded_picks", "drafts")}
        weeks = [get(f"{A}/v1/league/{lid}/matchups/{w}") for w in range(1, 19)]
        out["leagues"].append({"league": lg, "users": parts["users"], "rosters": parts["rosters"],
                               "winners_bracket": parts["winners_bracket"], "losers_bracket": parts["losers_bracket"],
                               "traded_picks": parts["traded_picks"], "drafts": parts["drafts"], "matchups": weeks})
        lid = lg.get("previous_league_id")

    players = get(f"{A}/v1/players/nfl") or {}
    rostered = set()
    for L in out["leagues"]:
        for r in L["rosters"] or []:
            rostered.update(r.get("players") or [])
        for wk in L["matchups"]:
            for m in wk or []:
                rostered.update(m.get("players") or [])
    out["players"] = {pid: {k: p[k] for k in KEEP if p.get(k) is not None}
                      for pid, p in players.items()
                      if pid in rostered or (p.get("position") in ("QB", "RB", "WR", "TE") and p.get("active"))}

    out["projections"] = {}
    for L in out["leagues"]:
        season = L["league"]["season"]
        out["projections"][season] = [slim(get(f"{A}/projections/nfl/{season}/{w}?season_type=regular&{POS}")) for w in range(1, 19)]

    json.dump(out, open("sleeper.json", "w"), separators=(",", ":"))
    print("seasons", [L["league"]["season"] for L in out["leagues"]], "players", len(out["players"]),
          "week", out["state"].get("week"))


if __name__ == "__main__":
    main()
