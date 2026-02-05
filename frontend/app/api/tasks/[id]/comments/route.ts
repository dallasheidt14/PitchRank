import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';

export interface TaskComment {
  id: string;
  task_id: string;
  author: string;
  content: string;
  created_at: string;
}

interface RouteParams {
  params: Promise<{ id: string }>;
}

// GET /api/tasks/[id]/comments - Get comments for a task
export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const { id: taskId } = await params;

    const { data, error } = await supabase
      .from('task_comments')
      .select('*')
      .eq('task_id', taskId)
      .order('created_at', { ascending: true });

    if (error) {
      console.error('Error fetching comments:', error);
      return NextResponse.json({ error: 'Failed to fetch comments' }, { status: 500 });
    }

    return NextResponse.json({ comments: data as TaskComment[] });
  } catch (e) {
    console.error('Comments API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// POST /api/tasks/[id]/comments - Add a comment to a task
export async function POST(request: NextRequest, { params }: RouteParams) {
  try {
    const { id: taskId } = await params;
    const body = await request.json();
    const { author, content } = body;

    if (!author || typeof author !== 'string') {
      return NextResponse.json({ error: 'Author is required' }, { status: 400 });
    }

    if (!content || typeof content !== 'string') {
      return NextResponse.json({ error: 'Content is required' }, { status: 400 });
    }

    // Check if task exists
    const { data: task, error: taskError } = await supabase
      .from('agent_tasks')
      .select('id')
      .eq('id', taskId)
      .single();

    if (taskError || !task) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    const { data, error } = await supabase
      .from('task_comments')
      .insert({
        task_id: taskId,
        author,
        content,
      })
      .select()
      .single();

    if (error) {
      console.error('Error creating comment:', error);
      return NextResponse.json({ error: 'Failed to create comment' }, { status: 500 });
    }

    return NextResponse.json({ comment: data as TaskComment }, { status: 201 });
  } catch (e) {
    console.error('Comments API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
