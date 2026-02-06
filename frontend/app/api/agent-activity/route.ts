import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';

interface AgentMessage {
  id: string;
  session_key: string;
  agent_name: string;
  agent_emoji: string;
  message_preview: string;
  full_message: string;
  message_type: string;
  created_at: string;
}

// GET - fetch recent agent activity from Supabase
export async function GET() {
  try {
    console.log('[AgentActivity] Fetching from Supabase');
    
    const { data, error } = await supabase
      .from('agent_activity')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(50);
    
    if (error) {
      console.error('[AgentActivity] Supabase error:', error);
      return NextResponse.json(
        { 
          error: 'Failed to fetch agent activity',
          messages: [], 
          count: 0,
          debug: { error: error.message }
        },
        { status: 500 }
      );
    }
    
    // Transform to match frontend expectations
    const messages = (data || []).map((row: any) => ({
      timestamp: row.created_at,
      agentName: row.agent_name,
      agentEmoji: row.agent_emoji,
      messagePreview: row.message_preview,
      fullMessage: row.full_message || row.message_preview,
      sessionId: row.session_key || 'unknown',
      messageType: row.message_type,
    }));
    
    console.log(`[AgentActivity] Returning ${messages.length} messages from Supabase`);
    
    return NextResponse.json({
      messages,
      count: messages.length,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('[AgentActivity] Unexpected error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to read agent activity', 
        messages: [], 
        count: 0,
        debug: { error: String(error) }
      },
      { status: 500 }
    );
  }
}

// POST - add new agent activity (called by webhook or agents)
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { 
      session_key, 
      agent_name, 
      agent_emoji, 
      message_preview, 
      full_message, 
      message_type 
    } = body;
    
    // Validate required fields
    if (!agent_name || !message_preview) {
      return NextResponse.json(
        { error: 'Missing required fields: agent_name, message_preview' },
        { status: 400 }
      );
    }
    
    console.log(`[AgentActivity] Logging ${message_type || 'message'} from ${agent_name}`);
    
    const { data, error } = await supabase
      .from('agent_activity')
      .insert({
        session_key: session_key || 'unknown',
        agent_name,
        agent_emoji: agent_emoji || '🤖',
        message_preview,
        full_message: full_message || message_preview,
        message_type: message_type || 'message',
      })
      .select()
      .single();
    
    if (error) {
      console.error('[AgentActivity] Insert error:', error);
      return NextResponse.json(
        { error: 'Failed to insert activity' },
        { status: 500 }
      );
    }
    
    return NextResponse.json({ 
      success: true, 
      activity: data 
    }, { status: 201 });
  } catch (error) {
    console.error('[AgentActivity] POST error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
