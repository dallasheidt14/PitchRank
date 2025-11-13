import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * API Route to process missing game requests
 * This can be called by Vercel Cron Jobs to run automatically
 * 
 * To set up Vercel Cron:
 * 1. Add to vercel.json:
 *    {
 *      "crons": [{
 *        "path": "/api/process-missing-games",
 *        "schedule": "every 5 minutes"
 *      }]
 *    }
 * 2. Or use Vercel Dashboard → Settings → Cron Jobs
 * 
 * Note: Processing is handled by GitHub Actions workflow, not this endpoint
 */
export async function GET(request: NextRequest) {
  try {
    // Verify this is a cron request (optional security check)
    const authHeader = request.headers.get('authorization');
    const cronSecret = process.env.CRON_SECRET;
    
    if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
      return NextResponse.json(
        { error: 'Unauthorized' },
        { status: 401 }
      );
    }

    const serviceKey = process.env.SUPABASE_SERVICE_KEY;
    if (!serviceKey) {
      console.error('[process-missing-games] Missing SUPABASE_SERVICE_KEY');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    if (!supabaseUrl) {
      console.error('[process-missing-games] Missing NEXT_PUBLIC_SUPABASE_URL');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    // Create Supabase client with service key
    const supabase = createClient(supabaseUrl, serviceKey);

    // Get pending requests
    const { data: pendingRequests, error: fetchError } = await supabase
      .from('scrape_requests')
      .select('*')
      .eq('status', 'pending')
      .eq('request_type', 'missing_game')
      .order('requested_at')
      .limit(10);

    if (fetchError) {
      console.error('[process-missing-games] Error fetching requests:', fetchError);
      return NextResponse.json(
        { error: 'Failed to fetch requests' },
        { status: 500 }
      );
    }

    if (!pendingRequests || pendingRequests.length === 0) {
      return NextResponse.json({
        success: true,
        message: 'No pending requests',
        processed: 0,
      });
    }

    // Note: This endpoint just triggers processing
    // The actual processing should be done by calling the Python script
    // For now, we'll return the pending requests count
    // In production, you'd want to:
    // 1. Call a separate service/function that runs the Python script
    // 2. Or use Supabase Edge Functions to run the processing logic
    // 3. Or use a service like GitHub Actions, AWS Lambda, etc.

    return NextResponse.json({
      success: true,
      message: `Found ${pendingRequests.length} pending requests`,
      pendingCount: pendingRequests.length,
      note: 'Processing should be handled by external service (Python script, Edge Function, etc.)',
    });
  } catch (error) {
    console.error('[process-missing-games] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}

