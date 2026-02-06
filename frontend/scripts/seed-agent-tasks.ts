/**
 * Seed Agent Tasks
 * Pre-populate Mission Control with recurring scheduled agent tasks
 * 
 * Usage: npx tsx scripts/seed-agent-tasks.ts
 */

import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  console.error('Missing Supabase environment variables');
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseAnonKey);

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

async function seedAgentTasks() {
  console.log('🌱 Seeding agent tasks...');

  // Check if tasks already exist (avoid duplicates)
  for (const task of seedTasks) {
    const { data: existing } = await supabase
      .from('agent_tasks')
      .select('id')
      .eq('title', task.title)
      .eq('assigned_agent', task.assigned_agent)
      .single();

    if (existing) {
      console.log(`⏭️  Skipping "${task.title}" - already exists`);
      continue;
    }

    const { data, error } = await supabase
      .from('agent_tasks')
      .insert(task)
      .select()
      .single();

    if (error) {
      console.error(`❌ Failed to create "${task.title}":`, error);
    } else {
      console.log(`✅ Created "${task.title}" (${data.id})`);
    }
  }

  console.log('\n✨ Seed complete!');
}

seedAgentTasks().catch((e) => {
  console.error('Seed error:', e);
  process.exit(1);
});
