import 'server-only';

import { createServiceSupabase } from '@/lib/supabase/service';
import type { MatchPredictionResponse, MatchPredictionShadowContext } from './matchPredictionService';

export interface MatchPredictionShadowLogInput {
  userId?: string | null;
  requestIp?: string | null;
  teamAId: string;
  teamBId: string;
  response: MatchPredictionResponse;
  shadowContext: MatchPredictionShadowContext;
}

function shadowLoggingEnabled(): boolean {
  return process.env.ENABLE_MATCH_PREDICTION_SHADOW_LOGGING === 'true';
}

export async function maybeLogMatchPredictionShadow(input: MatchPredictionShadowLogInput): Promise<void> {
  if (!shadowLoggingEnabled()) {
    return;
  }

  try {
    const supabase = createServiceSupabase();
    const payload = {
      user_id: input.userId ?? null,
      request_ip: input.requestIp ?? null,
      team_a_id: input.teamAId,
      team_b_id: input.teamBId,
      predictor_version: input.shadowContext.predictorVersion,
      shadow_status: 'pending',
      live_response: input.response,
      team_a_input: input.shadowContext.teamAInput,
      team_b_input: input.shadowContext.teamBInput,
      request_context: {
        resolvedTeamAIds: input.shadowContext.resolvedTeamAIds,
        resolvedTeamBIds: input.shadowContext.resolvedTeamBIds,
        relevantGameIds: input.shadowContext.relevantGameIds,
        relevantGameCount: input.shadowContext.relevantGameCount,
      },
    };

    const { error } = await supabase.from('match_prediction_shadow_log').insert(payload);
    if (error) {
      throw error;
    }
  } catch (error) {
    console.error('[matchPredictionShadow] Failed to log shadow prediction payload:', error);
  }
}
