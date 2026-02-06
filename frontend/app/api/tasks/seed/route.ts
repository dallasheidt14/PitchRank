import { NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';

const seedTasks = [
  {
    title: 'Weekly Data Hygiene',
    assigned_agent: 'cleany',
    status: 'assigned',
    priority: 'medium',
    description: 'Cleany runs every Sunday 7pm - club normalization, team deduplication',
    created_by: 'system',
  },
  {
    title: 'Daily Health Check',
    assigned_agent: 'watchy',
    status: 'assigned',
    priority: 'high',
    description: 'Watchy runs daily 8am - checks pipeline health, alerts on issues',
    created_by: 'system',
  },
  {
    title: 'Nightly Knowledge Extraction',
    assigned_agent: 'compy',
    status: 'assigned',
    priority: 'low',
    description: 'COMPY runs nightly 10:30pm - extracts learnings from agent sessions',
    created_by: 'system',
  },
  {
    title: 'Tuesday Movers Report',
    assigned_agent: 'movy',
    status: 'assigned',
    priority: 'medium',
    description: 'Movy runs Tuesday 10am - biggest ranking changes',
    created_by: 'system',
  },
];

/**
 * POST /api/tasks/seed
 * Seed the database with initial recurring agent tasks
 * Returns: { created: number, skipped: number, tasks: Task[] }
 */
export async function POST() {
  try {
    const results = {
      created: 0,
      skipped: 0,
      tasks: [] as any[],
    };

    for (const task of seedTasks) {
      // Check if task already exists
      const { data: existing } = await supabase
        .from('agent_tasks')
        .select('id, title')
        .eq('title', task.title)
        .eq('assigned_agent', task.assigned_agent)
        .single();

      if (existing) {
        console.log(`Skipping "${task.title}" - already exists`);
        results.skipped++;
        results.tasks.push(existing);
        continue;
      }

      // Create new task
      const { data, error } = await supabase
        .from('agent_tasks')
        .insert(task)
        .select()
        .single();

      if (error) {
        console.error(`Failed to create "${task.title}":`, error);
        return NextResponse.json(
          { error: `Failed to create task: ${task.title}`, details: error },
          { status: 500 }
        );
      }

      console.log(`Created "${task.title}"`);
      results.created++;
      results.tasks.push(data);
    }

    return NextResponse.json({
      success: true,
      ...results,
      message: `Created ${results.created} tasks, skipped ${results.skipped} existing`,
    });
  } catch (e) {
    console.error('Seed API error:', e);
    return NextResponse.json(
      { error: 'Internal server error', details: String(e) },
      { status: 500 }
    );
  }
}

/**
 * GET /api/tasks/seed
 * Preview what tasks would be seeded
 */
export async function GET() {
  return NextResponse.json({
    seedTasks,
    count: seedTasks.length,
    message: 'POST to this endpoint to seed these tasks',
  });
}
