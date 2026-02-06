import { Resend } from 'resend';

const resend = new Resend(process.env.RESEND_API_KEY);

interface WatchlistTeamChange {
  team_name: string;
  rank_change_7d: number;
  current_rank: number;
  power_score: number;
}

interface DigestData {
  email: string;
  user_name?: string;
  teams: WatchlistTeamChange[];
}

/**
 * Send a weekly digest email summarizing watchlist ranking changes
 */
export async function sendWeeklyDigest(data: DigestData) {
  if (!process.env.RESEND_API_KEY) {
    console.warn('RESEND_API_KEY not set — skipping digest email');
    return;
  }

  const { email, user_name, teams } = data;

  const movers = teams.filter((t) => t.rank_change_7d !== 0);
  const climbers = movers.filter((t) => t.rank_change_7d > 0).sort((a, b) => b.rank_change_7d - a.rank_change_7d);
  const fallers = movers.filter((t) => t.rank_change_7d < 0).sort((a, b) => a.rank_change_7d - b.rank_change_7d);

  const teamRows = teams
    .map((t) => {
      const arrow = t.rank_change_7d > 0 ? '↑' : t.rank_change_7d < 0 ? '↓' : '—';
      const color = t.rank_change_7d > 0 ? '#16a34a' : t.rank_change_7d < 0 ? '#ef4444' : '#6b7280';
      const changeText = t.rank_change_7d !== 0 ? `${arrow} ${Math.abs(t.rank_change_7d)}` : '—';
      return `<tr>
        <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">${t.team_name}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">#${t.current_rank}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;color:${color};font-weight:600;">${changeText}</td>
      </tr>`;
    })
    .join('');

  const html = `
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:linear-gradient(135deg,#1B4D3E,#0D2818);padding:24px 32px;border-radius:8px 8px 0 0;">
        <h1 style="color:#FFD700;font-size:14px;letter-spacing:3px;margin:0;">PITCHRANK</h1>
        <h2 style="color:#fff;font-size:24px;margin:8px 0 0;">Weekly Rankings Digest</h2>
      </div>
      <div style="padding:24px 32px;background:#fff;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
        <p style="color:#374151;">Hi${user_name ? ` ${user_name}` : ''},</p>
        <p style="color:#374151;">Here's how your watchlist teams performed this week:</p>

        ${climbers.length > 0 ? `<p style="color:#16a34a;font-weight:600;">🚀 ${climbers.length} team${climbers.length > 1 ? 's' : ''} moved up</p>` : ''}
        ${fallers.length > 0 ? `<p style="color:#ef4444;font-weight:600;">📉 ${fallers.length} team${fallers.length > 1 ? 's' : ''} moved down</p>` : ''}
        ${movers.length === 0 ? `<p style="color:#6b7280;">No ranking changes this week — steady as she goes.</p>` : ''}

        <table style="width:100%;border-collapse:collapse;margin:16px 0;">
          <thead>
            <tr style="background:#f9fafb;">
              <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #1B4D3E;font-size:13px;color:#6b7280;">Team</th>
              <th style="padding:8px 12px;text-align:center;border-bottom:2px solid #1B4D3E;font-size:13px;color:#6b7280;">Rank</th>
              <th style="padding:8px 12px;text-align:center;border-bottom:2px solid #1B4D3E;font-size:13px;color:#6b7280;">7d Change</th>
            </tr>
          </thead>
          <tbody>${teamRows}</tbody>
        </table>

        <a href="https://pitchrank.io/watchlist" style="display:inline-block;background:#1B4D3E;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;margin-top:12px;">View Full Watchlist</a>

        <p style="color:#9ca3af;font-size:12px;margin-top:24px;">
          You're receiving this because you have email digests enabled on PitchRank.<br/>
          <a href="https://pitchrank.io/account" style="color:#1B4D3E;">Manage notification preferences</a>
        </p>
      </div>
    </div>
  `;

  await resend.emails.send({
    from: 'PitchRank <digest@pitchrank.io>',
    to: email,
    subject: `📊 PitchRank Weekly: ${climbers.length > 0 ? `${climbers[0].team_name} moved up ${climbers[0].rank_change_7d} spots!` : 'Your Watchlist Update'}`,
    html,
  });
}
