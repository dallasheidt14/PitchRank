import type { Metadata } from 'next';
import { api } from '@/lib/api';

// Revalidate every hour
export const revalidate = 3600;

interface ClubEmbedPageProps {
  params: Promise<{
    clubId: string; // URL-encoded club name
  }>;
}

/**
 * Generate metadata for embed pages
 */
export async function generateMetadata({ params }: ClubEmbedPageProps): Promise<Metadata> {
  const resolvedParams = await params;
  const clubName = decodeURIComponent(resolvedParams.clubId);

  return {
    title: `${clubName} Teams | PitchRank`,
    description: `View ${clubName} youth soccer team rankings on PitchRank`,
  };
}

export default async function ClubEmbedPage({ params }: ClubEmbedPageProps) {
  const resolvedParams = await params;
  const clubName = decodeURIComponent(resolvedParams.clubId);
  
  // Fetch all teams from this club
  let teams: Array<{
    team_id_master: string;
    team_name: string;
    age: number;
    gender: 'M' | 'F' | 'B' | 'G';
    state: string | null;
    power_score_final: number;
    rank_in_cohort_final: number;
    rank_in_state_final?: number;
    wins: number;
    losses: number;
    draws: number;
  }> = [];

  try {
    // Get all rankings and filter by club name
    // We need to fetch across all age groups and genders
    const allRankings = await api.getRankings(null, undefined, null);
    teams = allRankings
      .filter(t => t.club_name?.toLowerCase() === clubName.toLowerCase())
      .map(t => ({
        team_id_master: t.team_id_master,
        team_name: t.team_name,
        age: t.age,
        gender: t.gender,
        state: t.state,
        power_score_final: t.power_score_final,
        rank_in_cohort_final: t.rank_in_cohort_final,
        rank_in_state_final: t.rank_in_state_final,
        wins: t.wins,
        losses: t.losses,
        draws: t.draws,
      }))
      .sort((a, b) => {
        // Sort by age then gender
        if (a.age !== b.age) return a.age - b.age;
        if (a.gender !== b.gender) return a.gender.localeCompare(b.gender);
        return b.power_score_final - a.power_score_final;
      });
  } catch (error) {
    console.error('Error fetching club teams:', error);
  }

  const formatGender = (g: string) => {
    if (g === 'M' || g === 'B') return 'Boys';
    if (g === 'F' || g === 'G') return 'Girls';
    return g;
  };

  return (
    <div style={{ padding: '16px' }}>
      <style dangerouslySetInnerHTML={{ __html: `
        .embed-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
          padding-bottom: 12px;
          border-bottom: 2px solid #10b981;
        }
        .embed-header h1 {
          font-size: 18px;
          font-weight: 700;
          color: #1a1a1a;
          margin: 0;
        }
        .embed-header a {
          font-size: 12px;
          color: #10b981;
          text-decoration: none;
        }
        .embed-header a:hover { text-decoration: underline; }
        .embed-table {
          width: 100%;
          border-collapse: collapse;
        }
        .embed-table th {
          text-align: left;
          padding: 8px 6px;
          background: #f5f5f5;
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          color: #666;
          border-bottom: 1px solid #ddd;
        }
        .embed-table td {
          padding: 8px 6px;
          border-bottom: 1px solid #eee;
          vertical-align: middle;
        }
        .embed-table tr:hover { background: #fafafa; }
        .team-link {
          font-weight: 500;
          color: #1a1a1a;
          text-decoration: none;
        }
        .team-link:hover { color: #10b981; }
        .meta-text {
          font-size: 12px;
          color: #888;
        }
        .score-text {
          font-family: 'SF Mono', Monaco, monospace;
          font-weight: 600;
          color: #10b981;
        }
        .rank-text {
          font-size: 12px;
          color: #666;
        }
        .empty-state {
          text-align: center;
          padding: 32px;
          color: #888;
        }
        .embed-footer {
          margin-top: 16px;
          padding-top: 12px;
          border-top: 1px solid #eee;
          text-align: center;
          font-size: 11px;
          color: #888;
        }
        .embed-footer a {
          color: #10b981;
          text-decoration: none;
          font-weight: 500;
        }
        .embed-footer a:hover { text-decoration: underline; }
      `}} />

      <div className="embed-header">
        <h1>{clubName}</h1>
        <a href={`https://pitchrank.io/teams?club=${encodeURIComponent(clubName)}`} target="_blank" rel="noopener noreferrer">
          View on PitchRank →
        </a>
      </div>

      {teams.length > 0 ? (
        <table className="embed-table">
          <thead>
            <tr>
              <th>Team</th>
              <th>Age</th>
              <th>Record</th>
              <th>Score</th>
              <th>Rank</th>
            </tr>
          </thead>
          <tbody>
            {teams.map(team => (
              <tr key={team.team_id_master}>
                <td>
                  <a 
                    href={`https://pitchrank.io/teams/${team.team_id_master}`} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="team-link"
                  >
                    {team.team_name}
                  </a>
                </td>
                <td className="meta-text">
                  U{team.age} {formatGender(team.gender)}
                </td>
                <td className="meta-text">
                  {team.wins}-{team.losses}-{team.draws}
                </td>
                <td className="score-text">
                  {team.power_score_final.toFixed(1)}
                </td>
                <td className="rank-text">
                  #{team.rank_in_cohort_final} National
                  {team.rank_in_state_final && team.state && (
                    <span className="meta-text"> / #{team.rank_in_state_final} {team.state}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="empty-state">
          No ranked teams found for {clubName}
        </div>
      )}

      <div className="embed-footer">
        Powered by <a href="https://pitchrank.io" target="_blank" rel="noopener noreferrer">PitchRank</a>
        {' '}• Youth Soccer Rankings
      </div>
    </div>
  );
}
