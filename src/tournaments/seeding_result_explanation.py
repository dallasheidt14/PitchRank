"""Short, attributable descriptions of a saved joint-results fit."""


def explain_results(profile: dict) -> str:
    games = profile.get("games", 0)
    opponents = profile.get("distinctOpponents", 0)
    if not games:
        return "No usable scored games; placement relies on the saved rating. Review required."
    facts = []
    observations = profile.get("influentialGames", [])
    # Show results above and below the rating prior when available.
    positive = next((row for row in observations if row["residual"] > 0), None)
    negative = next((row for row in observations if row["residual"] < 0), None)
    selected = [row for row in (positive, negative) if row] or observations[:1]
    for row in selected:
        goals = row["fixture"]["goals"]
        scored, conceded = int((goals + row["margin"]) / 2), int((goals - row["margin"]) / 2)
        name = row["opponent_name"]
        club = row.get("opponent_club", "")
        opponent = f"{club} {name}" if club and club.casefold() not in name.casefold() else name
        facts.append(f"{scored}-{conceded} vs {opponent} ({row['date']})")
    prefix = f"{games} games / {opponents} opponents; latest {profile.get('latestGameDate')}"
    caution = " Limited evidence." if profile.get("limited") else ""
    if profile.get("componentEntrants", 0) < 2:
        caution += " No shared-result link to another entrant."
    return prefix + ". " + "; ".join(facts) + "." + caution
