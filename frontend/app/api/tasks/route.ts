import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';

export interface AgentTask {
  id: string;
  title: string;
  description: string | null;
  status: 'inbox' | 'assigned' | 'in_progress' | 'review' | 'done';
  assigned_agent: string | null;
  created_by: string;
  priority: 'low' | 'medium' | 'high';
  created_at: string;
  updated_at: string;
}

// GET /api/tasks - List all tasks
export async function GET() {
  try {
    const { data, error } = await supabase
      .from('agent_tasks')
      .select('*')
      .order('created_at', { ascending: false });

    if (error) {
      console.error('Error fetching tasks:', error);
      return NextResponse.json({ error: 'Failed to fetch tasks' }, { status: 500 });
    }

    return NextResponse.json({ tasks: data as AgentTask[] });
  } catch (e) {
    console.error('Tasks API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// POST /api/tasks - Create a new task
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { title, description, assigned_agent, created_by, priority } = body;

    if (!title || typeof title !== 'string') {
      return NextResponse.json({ error: 'Title is required' }, { status: 400 });
    }

    // Determine initial status based on assignment
    // If assigned, start in 'assigned' status; otherwise 'inbox'
    const initialStatus = assigned_agent ? 'assigned' : 'inbox';

    const { data, error } = await supabase
      .from('agent_tasks')
      .insert({
        title,
        description: description || null,
        assigned_agent: assigned_agent || null,
        created_by: created_by || 'orchestrator',
        priority: priority || 'medium',
        status: initialStatus,
      })
      .select()
      .single();

    if (error) {
      console.error('Error creating task:', error);
      return NextResponse.json({ error: 'Failed to create task' }, { status: 500 });
    }

    return NextResponse.json({ task: data as AgentTask }, { status: 201 });
  } catch (e) {
    console.error('Tasks API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
