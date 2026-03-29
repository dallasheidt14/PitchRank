import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';
import { requireAdmin } from '@/lib/supabase/admin';

interface RouteParams {
  params: Promise<{ id: string }>;
}

// GET /api/tasks/[id] - Get a single task
export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

    const { id } = await params;

    const { data, error } = await supabase.from('agent_tasks').select('*').eq('id', id).single();

    if (error || !data) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    return NextResponse.json({ task: data });
  } catch (e) {
    console.error('Task API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// PATCH /api/tasks/[id] - Update a task
export async function PATCH(request: NextRequest, { params }: RouteParams) {
  try {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

    const { id } = await params;
    const body = await request.json();
    const { title, description, status, assigned_agent, priority } = body;

    // Validate field values
    const VALID_STATUSES = ['inbox', 'in_progress', 'assigned', 'review', 'done'];
    const VALID_PRIORITIES = ['low', 'medium', 'high', 'urgent'];

    if (status !== undefined && !VALID_STATUSES.includes(status)) {
      return NextResponse.json(
        { error: `Invalid status. Must be one of: ${VALID_STATUSES.join(', ')}` },
        { status: 400 }
      );
    }

    if (priority !== undefined && !VALID_PRIORITIES.includes(priority)) {
      return NextResponse.json(
        { error: `Invalid priority. Must be one of: ${VALID_PRIORITIES.join(', ')}` },
        { status: 400 }
      );
    }

    if (title !== undefined && (typeof title !== 'string' || title.length > 200)) {
      return NextResponse.json({ error: 'Title must be a string of 200 characters or fewer' }, { status: 400 });
    }

    if (assigned_agent !== undefined && (typeof assigned_agent !== 'string' || assigned_agent.trim() === '')) {
      return NextResponse.json({ error: 'assigned_agent must be a non-empty string' }, { status: 400 });
    }

    // Build update object with only provided fields
    const updates: Record<string, unknown> = {};
    if (title !== undefined) updates.title = title;
    if (description !== undefined) updates.description = description;
    if (status !== undefined) updates.status = status;
    if (assigned_agent !== undefined) updates.assigned_agent = assigned_agent;
    if (priority !== undefined) updates.priority = priority;

    if (Object.keys(updates).length === 0) {
      return NextResponse.json({ error: 'No fields to update' }, { status: 400 });
    }

    const { data, error } = await supabase.from('agent_tasks').update(updates).eq('id', id).select().single();

    if (error) {
      console.error('Error updating task:', error);
      return NextResponse.json({ error: 'Failed to update task' }, { status: 500 });
    }

    if (!data) {
      return NextResponse.json({ error: 'Task not found' }, { status: 404 });
    }

    return NextResponse.json({ task: data });
  } catch (e) {
    console.error('Task API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// DELETE /api/tasks/[id] - Delete a task
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  try {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

    const { id } = await params;

    const { error } = await supabase.from('agent_tasks').delete().eq('id', id);

    if (error) {
      console.error('Error deleting task:', error);
      return NextResponse.json({ error: 'Failed to delete task' }, { status: 500 });
    }

    return NextResponse.json({ success: true });
  } catch (e) {
    console.error('Task API error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
