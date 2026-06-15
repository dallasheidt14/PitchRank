import { createServerSupabase } from '@/lib/supabase/server';
import { sendReportCardEmail } from '@/lib/email';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { optionalAuth } from '@/lib/api/optionalAuth';
import { subscribeFreeLead, enrollInAutomation } from '@/lib/beehiiv';
import { formatTeamRecord } from '@/lib/reports/team-record';
import { isValidUuid, isValidEmail } from '@/lib/validation';
import { NextRequest, NextResponse } from 'next/server';
import { renderToBuffer } from '@react-pdf/renderer';
import { TeamReportCard } from '@/lib/pdf';
import type { ReportCardGame } from '@/lib/pdf';
import React from 'react';

export async function POST(request: NextRequest) {
  try {
    const ip = getClientIp(request);
    if (!checkRateLimit(`team-card:${ip}`, 3, 60000)) {
      return NextResponse.json({ error: 'Too many requests. Please try again later.' }, { status: 429 });
    }

    await optionalAuth();

    const body = await request.json();
    const { teamId, email, role } = body;

    // Validate inputs
    if (!teamId || typeof teamId !== 'string' || !isValidUuid(teamId)) {
      return NextResponse.json({ error: 'Invalid team ID' }, { status: 400 });
    }
    if (!email || typeof email !== 'string' || !isValidEmail(email)) {
      return NextResponse.json({ error: 'Please enter a valid email address' }, { status: 400 });
    }

    const normalizedEmail = email.toLowerCase().trim();
    const supabase = await createServerSupabase();

    // Fetch team data
    const { data: team, error: teamError } = await supabase
      .from('teams')
      .select('team_id_master, team_name, club_name, state_code, age_group, gender')
      .eq('team_id_master', teamId)
      .single();

    if (teamError || !team) {
      return NextResponse.json({ error: 'Team not found' }, { status: 404 });
    }

    // Fetch ranking data (includes rank_change_*, perf_centered, offense_norm, defense_norm)
    const { data: ranking, error: rankingError } = await supabase
      .from('rankings_view')
      .select('*')
      .eq('team_id_master', teamId)
      .single();

    // rank_in_cohort_final is null for non-Active teams; without it the
    // percentile math below degenerates to "top 100% nationally"
    if (rankingError || !ranking || ranking.power_score_final == null || ranking.rank_in_cohort_final == null) {
      return NextResponse.json(
        { error: 'Not enough ranking data for this team. Check back after they have played more games.' },
        { status: 400 }
      );
    }

    // Fetch last 5 games with opponent names
    const { data: rawGames } = await supabase
      .from('games')
      .select('game_date, home_team_master_id, away_team_master_id, home_score, away_score')
      .or(`home_team_master_id.eq.${teamId},away_team_master_id.eq.${teamId}`)
      .eq('is_excluded', false)
      .not('home_score', 'is', null)
      .not('away_score', 'is', null)
      .order('game_date', { ascending: false })
      .limit(5);

    // Resolve opponent names
    const games: ReportCardGame[] = [];
    if (rawGames && rawGames.length > 0) {
      const opponentIds = rawGames
        .map((g) => (g.home_team_master_id === teamId ? g.away_team_master_id : g.home_team_master_id))
        .filter(Boolean) as string[];

      const { data: opponents } = await supabase
        .from('teams')
        .select('team_id_master, team_name')
        .in('team_id_master', [...new Set(opponentIds)]);

      const nameMap = new Map<string, string>();
      opponents?.forEach((t) => nameMap.set(t.team_id_master, t.team_name));

      for (const g of rawGames) {
        const isHome = g.home_team_master_id === teamId;
        const opId = isHome ? g.away_team_master_id : g.home_team_master_id;
        const teamScore = isHome ? g.home_score : g.away_score;
        const oppScore = isHome ? g.away_score : g.home_score;
        let result: 'W' | 'L' | 'D' | 'U' = 'U';
        if (teamScore != null && oppScore != null) {
          if (teamScore > oppScore) result = 'W';
          else if (teamScore < oppScore) result = 'L';
          else result = 'D';
        }
        games.push({
          game_date: g.game_date
            ? new Date(g.game_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            : '—',
          opponent_name: (opId ? nameMap.get(opId) : null) || 'Unknown',
          score: `${teamScore ?? 0}-${oppScore ?? 0}`,
          result,
        });
      }
    }

    // Fetch cohort totals for percentile calculation
    const ageNum = parseInt(team.age_group?.replace('u', '') || '0', 10);
    const genderCode = team.gender === 'Male' ? 'M' : team.gender === 'Female' ? 'F' : team.gender;

    const { count: cohortTotal } = await supabase
      .from('rankings_view')
      .select('*', { count: 'exact', head: true })
      .eq('age', ageNum)
      .eq('gender', genderCode)
      .eq('status', 'Active');

    const { count: stateCohortTotal } = await supabase
      .from('rankings_view')
      .select('*', { count: 'exact', head: true })
      .eq('age', ageNum)
      .eq('gender', genderCode)
      .eq('state', team.state_code)
      .eq('status', 'Active');

    const totalNational = cohortTotal ?? 1;
    const totalState = stateCohortTotal ?? 1;

    // Generate PDF
    const generatedDate = new Date().toLocaleDateString('en-US', {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    });

    const pdfElement = React.createElement(TeamReportCard, {
      team: {
        team_name: team.team_name,
        club_name: team.club_name,
        state: team.state_code,
        age: ageNum,
        gender: genderCode,
      },
      ranking: {
        power_score_final: ranking.power_score_final,
        rank_in_cohort_final: ranking.rank_in_cohort_final,
        rank_in_state_final: ranking.rank_in_state_final ?? null,
        offense_norm: ranking.offense_norm ?? null,
        defense_norm: ranking.defense_norm ?? null,
        sos_norm: ranking.sos_norm ?? 0,
        rank_change_7d: ranking.rank_change_7d ?? null,
        rank_change_30d: ranking.rank_change_30d ?? null,
        rank_change_state_7d: ranking.rank_change_state_7d ?? null,
        rank_change_state_30d: ranking.rank_change_state_30d ?? null,
        perf_centered: ranking.perf_centered ?? null,
        wins: ranking.wins ?? 0,
        losses: ranking.losses ?? 0,
        draws: ranking.draws ?? 0,
        games_played: ranking.games_played ?? 0,
        total_wins: ranking.total_wins ?? 0,
        total_losses: ranking.total_losses ?? 0,
        total_draws: ranking.total_draws ?? 0,
        total_games_played: ranking.total_games_played ?? 0,
        win_percentage: ranking.win_percentage ?? null,
      },
      games,
      cohortTotal: totalNational,
      stateCohortTotal: totalState,
      generatedDate,
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const pdfBuffer = await renderToBuffer(pdfElement as any);

    // Save lead to database (non-blocking pattern)
    supabase
      .from('report_card_leads')
      .insert([
        {
          email: normalizedEmail,
          team_id: teamId,
          team_name: team.team_name,
          role: role || null,
          source: 'report-card',
        },
      ])
      .then(({ error: insertError }) => {
        if (insertError) console.error('Failed to save report card lead:', insertError);
      });

    // Sync lead to Beehiiv as free-tier subscriber for nurture automation (non-blocking).
    // Then explicitly enroll in the report-card automation so existing subscribers
    // (newsletter signups, Stripe premium-tier syncs) also enter the sequence — the
    // create-subscription branch only fires for brand-new emails.
    const reportCardAutomationId = process.env.BEEHIIV_REPORT_CARD_AUTOMATION_ID;
    subscribeFreeLead(normalizedEmail, {
      teamName: team.team_name,
      clubName: team.club_name,
      state: team.state_code,
      ageGroup: team.age_group,
      gender: team.gender,
      role: role || null,
    })
      .then(() => {
        if (reportCardAutomationId) {
          return enrollInAutomation(normalizedEmail, reportCardAutomationId);
        }
      })
      .catch((err) => {
        console.error('Failed to sync report card lead to Beehiiv:', err);
      });

    // Send email with PDF attachment (non-blocking)
    const record = formatTeamRecord(ranking);
    const percentile = Math.round((1 - ranking.rank_in_cohort_final / totalNational) * 100);

    sendReportCardEmail(
      normalizedEmail,
      team.team_name,
      ranking.rank_in_cohort_final,
      ranking.rank_in_state_final ?? null,
      team.state_code,
      ranking.power_score_final,
      percentile > 0 ? percentile : 1,
      record,
      ranking.rank_change_30d ?? null,
      Buffer.from(pdfBuffer)
    ).catch((err) => {
      console.error('Failed to send report card email:', err);
    });

    return NextResponse.json({ success: true, message: 'Report card sent! Check your inbox.' }, { status: 201 });
  } catch (error) {
    console.error('Report card API error:', error);
    return NextResponse.json({ error: 'An unexpected error occurred. Please try again.' }, { status: 500 });
  }
}
