import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';

export interface Announcement {
  id: string;
  message: string;
  author: string;
  created_at: string;
}

// GET /api/announcements - Get announcements (latest first)
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get('limit') || '10', 10);

    const { data, error } = await supabase
      .from('announcements')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(limit);

    if (error) {
      console.error('Error fetching announcements:', error);
      return NextResponse.json({ error: 'Failed to fetch announcements' }, { status: 500 });
    }

    return NextResponse.json({ announcements: data as Announcement[] });
  } catch (e) {
    console.error('Announcements API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// POST /api/announcements - Create a new announcement
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { message, author } = body;

    if (!message || typeof message !== 'string') {
      return NextResponse.json({ error: 'Message is required' }, { status: 400 });
    }

    const { data, error } = await supabase
      .from('announcements')
      .insert({
        message,
        author: author || 'D H',
      })
      .select()
      .single();

    if (error) {
      console.error('Error creating announcement:', error);
      return NextResponse.json({ error: 'Failed to create announcement' }, { status: 500 });
    }

    return NextResponse.json({ announcement: data as Announcement }, { status: 201 });
  } catch (e) {
    console.error('Announcements API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
