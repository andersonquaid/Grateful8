# GRateful 8 League Hub

Standings, playoff and Toilet Bowl brackets, rookie draft order and record books for the GRateful 8 Sleeper league.

**Site:** https://andersonquaid.github.io/Grateful8/

## How it stays current

A GitHub Action (`.github/workflows/refresh.yml`) runs every Tuesday at 5:03 AM Eastern (daylight or standard time). It pulls the league from the public Sleeper API, rebuilds `index.html`, commits it to `main`, and publishes it to the `gh-pages` branch, which GitHub Pages serves. The site updates a minute or two later. To refresh on demand: **Actions → Refresh league hub → Run workflow**.

## Files

- `index.html`: the published page (generated; don't edit by hand)
- `build/collect_sleeper.py`: pulls league, rosters, matchups, brackets, traded picks, players and weekly projections into `sleeper.json`
- `build/build_league.py`: standings, records, draft order and a 20,000-season simulation (used for the projected-season toggle)
- `build/build_league_edition.py` + `build/league_template.html`: builds the page
- `build/league_admin.json`: League Admin tab content (important dates, rules, rule votes, dues and payouts) from the Official League Rulebook v2026 and the 2026 season calendar. Edit this file to change that tab; weekly high-score winners fill in automatically.

## League rules the page encodes

- Rookie draft picks 1–4: non-playoff teams, lowest Max PF first. Picks 5–8: playoff finish, champion picks 8th. During the season the Draft tab shows the order "if the season ended today."
- 2.09 goes to the Toilet Bowl winner: round-1 winners meet in the final. Round-1 losers play for last place, and the loser takes the punishment. (Sleeper tracks this bracket losers-advance for the punishment, so the build reads winners from scores.)
- 3.09 goes to the team with the most points against in the regular season.

The build follows the league into new seasons through Sleeper's `previous_league_id` chain. Before a new season's first game there are no matchups yet, so the page may need a check then.
