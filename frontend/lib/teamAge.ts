/** Soccer season year, rolling over on August 1. */
export function soccerSeasonYear(): number {
  const now = new Date();
  return now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1;
}

/** Extract a cohort age from a registered team name. */
export function extractAgeFromTeamName(teamName: string | null | undefined): number | null {
  if (!teamName) return null;

  const uMatch = teamName.match(/\bU(\d{1,2})\b/i);
  if (uMatch) {
    const age = parseInt(uMatch[1], 10);
    if (age >= 8 && age <= 19) return age;
  }

  const seasonYear = soccerSeasonYear();
  const birthYearMatch = teamName.match(/\b(0[89]|1[0-9])[BG]\b/i);
  if (birthYearMatch) {
    const ageGroup = seasonYear - (2000 + parseInt(birthYearMatch[1], 10)) + 1;
    if (ageGroup >= 6 && ageGroup <= 19) return ageGroup;
  }

  const standaloneMatch = teamName.match(/\b(0[89]|1[0-9])\b/);
  if (standaloneMatch) {
    const ageGroup = seasonYear - (2000 + parseInt(standaloneMatch[1], 10)) + 1;
    if (ageGroup >= 6 && ageGroup <= 19) return ageGroup;
  }

  return null;
}
