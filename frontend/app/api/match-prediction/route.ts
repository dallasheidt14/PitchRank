import { parseJsonBody } from '@/lib/api/parseJsonBody';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { requirePremium } from '@/lib/api/requirePremium';
import { AppError } from '@/lib/errors';
import { buildMatchPredictionWithShadowContext } from '@/lib/matchPredictionService';
import { maybeLogMatchPredictionShadow } from '@/lib/matchPredictionShadow';
import { isValidUuid } from '@/lib/validation';
import { NextRequest, NextResponse } from 'next/server';

interface MatchPredictionRequest {
  teamAId?: string;
  teamBId?: string;
}

export async function POST(request: NextRequest) {
  try {
    const ip = getClientIp(request);
    if (!checkRateLimit(`match-prediction:${ip}`, 10, 60_000)) {
      return NextResponse.json({ error: 'Too many requests. Please try again later.' }, { status: 429 });
    }

    const body = await parseJsonBody<MatchPredictionRequest>(request);
    if (body.error) {
      return body.error;
    }

    const { teamAId, teamBId } = body.data;

    if (!teamAId || typeof teamAId !== 'string' || !isValidUuid(teamAId)) {
      return NextResponse.json({ error: 'Invalid Team A ID' }, { status: 400 });
    }

    if (!teamBId || typeof teamBId !== 'string' || !isValidUuid(teamBId)) {
      return NextResponse.json({ error: 'Invalid Team B ID' }, { status: 400 });
    }

    if (teamAId === teamBId) {
      return NextResponse.json({ error: 'Please choose two different teams.' }, { status: 400 });
    }

    const auth = await requirePremium();
    if (auth.error) {
      return auth.error;
    }

    const result = await buildMatchPredictionWithShadowContext(auth.supabase, teamAId, teamBId);
    void maybeLogMatchPredictionShadow({
      userId: auth.user.id,
      requestIp: ip,
      teamAId,
      teamBId,
      response: result.response,
      shadowContext: result.shadowContext,
    });
    return NextResponse.json(result.response);
  } catch (error) {
    if (error instanceof AppError && error.statusCode) {
      return NextResponse.json({ error: error.message }, { status: error.statusCode });
    }

    console.error('[api/match-prediction] Failed to build prediction:', error);
    return NextResponse.json({ error: 'Failed to generate match prediction' }, { status: 500 });
  }
}
