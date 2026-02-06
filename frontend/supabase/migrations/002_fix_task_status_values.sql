-- Fix agent_tasks status values to match the code
-- The code expects: 'inbox', 'assigned', 'in_progress', 'review', 'done'
-- But the schema was: 'todo', 'in_progress', 'done'

-- First, drop the existing constraint
ALTER TABLE agent_tasks DROP CONSTRAINT IF EXISTS agent_tasks_status_check;

-- Update existing values if any
UPDATE agent_tasks SET status = 'inbox' WHERE status = 'todo';

-- Add the new constraint with all status values
ALTER TABLE agent_tasks ADD CONSTRAINT agent_tasks_status_check 
  CHECK (status IN ('inbox', 'assigned', 'in_progress', 'review', 'done'));

-- Update default value
ALTER TABLE agent_tasks ALTER COLUMN status SET DEFAULT 'inbox';
