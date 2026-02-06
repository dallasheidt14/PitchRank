import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error('Missing Supabase environment variables');
}

const supabase = createClient(supabaseUrl, supabaseAnonKey);

/**
 * GET /api/chat
 * Retrieve the last 50 messages from mission_chat
 */
export async function GET() {
  try {
    const { data, error } = await supabase
      .from('mission_chat')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(50);

    if (error) {
      console.error('Error fetching chat messages:', error);
      return NextResponse.json(
        { error: 'Failed to fetch messages' },
        { status: 500 }
      );
    }

    // Reverse to show oldest first
    const messages = (data || []).reverse();

    return NextResponse.json({ messages });
  } catch (e) {
    console.error('Unexpected error:', e);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

/**
 * POST /api/chat
 * Send a new message
 * Body: { author: string, author_type: 'human' | 'agent', content: string }
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { author, author_type = 'human', content } = body;

    if (!author || !content) {
      return NextResponse.json(
        { error: 'Missing required fields: author and content' },
        { status: 400 }
      );
    }

    if (author_type !== 'human' && author_type !== 'agent') {
      return NextResponse.json(
        { error: 'author_type must be either "human" or "agent"' },
        { status: 400 }
      );
    }

    const { data, error } = await supabase
      .from('mission_chat')
      .insert([
        {
          author,
          author_type,
          content,
        },
      ])
      .select()
      .single();

    if (error) {
      console.error('Error inserting chat message:', error);
      return NextResponse.json(
        { error: 'Failed to send message' },
        { status: 500 }
      );
    }

    return NextResponse.json({ message: data });
  } catch (e) {
    console.error('Unexpected error:', e);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
