/**
 * Integration test to verify rankings_view and state_rankings_view
 * match the canonical data contract.
 * 
 * Run with: npx tsx tests/integration/verify_rankings_views.test.ts
 * Or: ts-node tests/integration/verify_rankings_views.test.ts
 * 
 * Requires environment variables:
 * - NEXT_PUBLIC_SUPABASE_URL
 * - NEXT_PUBLIC_SUPABASE_ANON_KEY (or SUPABASE_SERVICE_KEY for full access)
 */

import { createClient } from '@supabase/supabase-js';

// Canonical fields that MUST be present in rankings_view
const RANKINGS_VIEW_CANONICAL_FIELDS = [
  'team_id_master',
  'team_name',
  'club_name',
  'state',           // alias for state_code
  'age',             // alias for age_group
  'gender',
  'games_played',
  'wins',
  'losses',
  'draws',
  'win_percentage',
  'power_score_final',
  'sos_norm',
  'offense_norm',
  'defense_norm',
  'rank_in_cohort_final',
] as const;

// Canonical fields that MUST be present in state_rankings_view
const STATE_RANKINGS_VIEW_CANONICAL_FIELDS = [
  ...RANKINGS_VIEW_CANONICAL_FIELDS,
  'rank_in_state_final',
] as const;

// Legacy fields that MUST NOT be present
const LEGACY_FIELDS = [
  'power_score',
  'national_power_score',
  'strength_of_schedule',
  'national_rank',
  'state_rank',
  'national_sos_rank',
  'state_sos_rank',
  'state_code',      // should be 'state' instead
  'age_group',       // should be 'age' instead
  'sos',             // legacy raw SOS field
] as const;

interface TestResult {
  passed: boolean;
  message: string;
  details?: any;
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`ASSERTION FAILED: ${message}`);
  }
}

async function testRankingsView(supabase: ReturnType<typeof createClient>): Promise<TestResult> {
  try {
    // Query rankings_view LIMIT 1
    const { data, error } = await supabase
      .from('rankings_view')
      .select('*')
      .limit(1);

    if (error) {
      return {
        passed: false,
        message: `Error querying rankings_view: ${error.message}`,
        details: error,
      };
    }

    if (!data || data.length === 0) {
      return {
        passed: false,
        message: 'rankings_view returned no data',
      };
    }

    const row = data[0];
    const actualFields = Object.keys(row);

    // Check all canonical fields exist
    const missingFields = RANKINGS_VIEW_CANONICAL_FIELDS.filter(
      field => !actualFields.includes(field)
    );

    if (missingFields.length > 0) {
      return {
        passed: false,
        message: `Missing canonical fields in rankings_view: ${missingFields.join(', ')}`,
        details: { missingFields, actualFields },
      };
    }

    // Check legacy fields are absent
    const presentLegacyFields = LEGACY_FIELDS.filter(
      field => actualFields.includes(field)
    );

    if (presentLegacyFields.length > 0) {
      return {
        passed: false,
        message: `Legacy fields found in rankings_view: ${presentLegacyFields.join(', ')}`,
        details: { presentLegacyFields, actualFields },
      };
    }

    // Verify required non-null fields
    const requiredNonNullFields: (keyof typeof row)[] = [
      'team_id_master',
      'team_name',
      'gender',
      'power_score_final',
      'sos_norm',
    ];

    const nullRequiredFields = requiredNonNullFields.filter(
      field => row[field] === null || row[field] === undefined
    );

    if (nullRequiredFields.length > 0) {
      return {
        passed: false,
        message: `Required fields are null in rankings_view: ${nullRequiredFields.join(', ')}`,
        details: { nullRequiredFields, row },
      };
    }

    // Verify field types
    assert(typeof row.team_id_master === 'string', 'team_id_master must be string');
    assert(typeof row.team_name === 'string', 'team_name must be string');
    assert(typeof row.power_score_final === 'number', 'power_score_final must be number');
    assert(typeof row.sos_norm === 'number', 'sos_norm must be number');
    assert(typeof row.rank_in_cohort_final === 'number', 'rank_in_cohort_final must be number');

    return {
      passed: true,
      message: 'rankings_view matches canonical contract',
      details: { fieldCount: actualFields.length, sampleRow: row },
    };
  } catch (error) {
    return {
      passed: false,
      message: `Exception testing rankings_view: ${error instanceof Error ? error.message : String(error)}`,
      details: error,
    };
  }
}

async function testStateRankingsView(supabase: ReturnType<typeof createClient>): Promise<TestResult> {
  try {
    // Query state_rankings_view LIMIT 1
    const { data, error } = await supabase
      .from('state_rankings_view')
      .select('*')
      .limit(1);

    if (error) {
      return {
        passed: false,
        message: `Error querying state_rankings_view: ${error.message}`,
        details: error,
      };
    }

    if (!data || data.length === 0) {
      return {
        passed: false,
        message: 'state_rankings_view returned no data',
      };
    }

    const row = data[0];
    const actualFields = Object.keys(row);

    // Check all canonical fields exist
    const missingFields = STATE_RANKINGS_VIEW_CANONICAL_FIELDS.filter(
      field => !actualFields.includes(field)
    );

    if (missingFields.length > 0) {
      return {
        passed: false,
        message: `Missing canonical fields in state_rankings_view: ${missingFields.join(', ')}`,
        details: { missingFields, actualFields },
      };
    }

    // Check legacy fields are absent
    const presentLegacyFields = LEGACY_FIELDS.filter(
      field => actualFields.includes(field)
    );

    if (presentLegacyFields.length > 0) {
      return {
        passed: false,
        message: `Legacy fields found in state_rankings_view: ${presentLegacyFields.join(', ')}`,
        details: { presentLegacyFields, actualFields },
      };
    }

    // Verify required non-null fields
    const requiredNonNullFields: (keyof typeof row)[] = [
      'team_id_master',
      'team_name',
      'gender',
      'power_score_final',
      'sos_norm',
      'rank_in_state_final',
    ];

    const nullRequiredFields = requiredNonNullFields.filter(
      field => row[field] === null || row[field] === undefined
    );

    if (nullRequiredFields.length > 0) {
      return {
        passed: false,
        message: `Required fields are null in state_rankings_view: ${nullRequiredFields.join(', ')}`,
        details: { nullRequiredFields, row },
      };
    }

    // Verify field types
    assert(typeof row.team_id_master === 'string', 'team_id_master must be string');
    assert(typeof row.team_name === 'string', 'team_name must be string');
    assert(typeof row.power_score_final === 'number', 'power_score_final must be number');
    assert(typeof row.sos_norm === 'number', 'sos_norm must be number');
    assert(typeof row.rank_in_cohort_final === 'number', 'rank_in_cohort_final must be number');
    assert(typeof row.rank_in_state_final === 'number', 'rank_in_state_final must be number');

    return {
      passed: true,
      message: 'state_rankings_view matches canonical contract',
      details: { fieldCount: actualFields.length, sampleRow: row },
    };
  } catch (error) {
    return {
      passed: false,
      message: `Exception testing state_rankings_view: ${error instanceof Error ? error.message : String(error)}`,
      details: error,
    };
  }
}

async function main() {
  console.log('🧪 Starting rankings views contract verification...\n');

  // Get Supabase credentials from environment
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseKey) {
    console.error('❌ Missing Supabase credentials');
    console.error('Required environment variables:');
    console.error('  - NEXT_PUBLIC_SUPABASE_URL or SUPABASE_URL');
    console.error('  - NEXT_PUBLIC_SUPABASE_ANON_KEY or SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY');
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  // Run tests
  const results: Array<{ name: string; result: TestResult }> = [];

  console.log('📊 Testing rankings_view...');
  const rankingsViewResult = await testRankingsView(supabase);
  results.push({ name: 'rankings_view', result: rankingsViewResult });
  console.log(rankingsViewResult.passed ? '✅' : '❌', rankingsViewResult.message);
  if (rankingsViewResult.details && !rankingsViewResult.passed) {
    console.log('   Details:', JSON.stringify(rankingsViewResult.details, null, 2));
  }

  console.log('\n📊 Testing state_rankings_view...');
  const stateRankingsViewResult = await testStateRankingsView(supabase);
  results.push({ name: 'state_rankings_view', result: stateRankingsViewResult });
  console.log(stateRankingsViewResult.passed ? '✅' : '❌', stateRankingsViewResult.message);
  if (stateRankingsViewResult.details && !stateRankingsViewResult.passed) {
    console.log('   Details:', JSON.stringify(stateRankingsViewResult.details, null, 2));
  }

  // Summary
  console.log('\n' + '='.repeat(60));
  const allPassed = results.every(r => r.result.passed);
  if (allPassed) {
    console.log('✅ All tests passed! Views match canonical contract.');
  } else {
    console.log('❌ Some tests failed. Please review the output above.');
    process.exit(1);
  }
}

// Run if executed directly
if (require.main === module) {
  main().catch(error => {
    console.error('❌ Fatal error:', error);
    process.exit(1);
  });
}

export { testRankingsView, testStateRankingsView };

