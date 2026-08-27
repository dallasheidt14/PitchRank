import { composeTeamMeta } from '@/lib/utils';

interface TeamRowSubtitleProps {
  team: { club_name?: string | null; state?: string | null; age?: number | null; gender?: string | null };
  /**
   * The query matches `club_name` too, and a row whose registered name shares no text with it
   * looks unrelated — so search rows pass a highlighter for the club.
   */
  highlight?: (text: string) => React.ReactNode;
  className?: string;
}

/**
 * "{club} • {state} • U{age} {gender}" under a team's name.
 *
 * `spokenTeamMeta` renders the same string for an `aria-label` — keep the two in sync.
 */
export function TeamRowSubtitle({ team, highlight, className }: TeamRowSubtitleProps) {
  const meta = composeTeamMeta(team);
  if (!team.club_name && !meta) return null;

  return (
    <div className={className}>
      {team.club_name && <span>{highlight ? highlight(team.club_name) : team.club_name}</span>}
      {team.club_name && meta ? ' • ' : ''}
      {meta}
    </div>
  );
}
