import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';

/**
 * Agent Webhook API
 * 
 * Receives notifications from OpenClaw agent sessions about task lifecycle events.
 * Used to automatically track sub-agent tasks in Mission Control.
 * 
 * Actions:
 * - spawn: Create a new in-progress task when an agent starts
 * - progress: Update task with progress info (optional)
 * - complete: Mark task done and add result comment
 * - error: Mark task as needs-retry and add error comment
 */

interface WebhookPayload {
  action: 'spawn' | 'progress' | 'complete' | 'error';
  sessionKey: string;
  agentName: string;
  task: string;
  result?: string;
  error?: string;
}

// Agent emoji mapping
const AGENT_EMOJIS: Record<string, string> = {
  scrappy: '🕷️',
  cleany: '🧹',
  watchy: '👀',
  compy: '🧠',
  ranky: '📊',
  movy: '🎬',
  codey: '💻',
  socialy: '📱',
  main: '🤖',
  subagent: '🔧',
};

function getAgentEmoji(agentName: string): string {
  const key = agentName.toLowerCase().replace(/\s+/g, '');
  return AGENT_EMOJIS[key] || '🤖';
}

// Simple auth check - can be enhanced with a shared secret
function validateRequest(request: NextRequest): boolean {
  // For now, allow localhost requests and check for optional webhook secret
  const webhookSecret = process.env.AGENT_WEBHOOK_SECRET;
  if (!webhookSecret) {
    // No secret configured, allow all requests (local dev)
    return true;
  }
  
  const authHeader = request.headers.get('authorization');
  return authHeader === `Bearer ${webhookSecret}`;
}

export async function POST(request: NextRequest) {
  try {
    // Validate request
    if (!validateRequest(request)) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body: WebhookPayload = await request.json();
    const { action, sessionKey, agentName, task, result, error: errorMsg } = body;

    // Validate required fields
    if (!action || !sessionKey || !agentName || !task) {
      return NextResponse.json(
        { error: 'Missing required fields: action, sessionKey, agentName, task' },
        { status: 400 }
      );
    }

    console.log(`[AgentWebhook] ${action} - ${agentName} (${sessionKey.substring(0, 8)})`);

    // Handle different actions
    switch (action) {
      case 'spawn': {
        // Create agent session record for live status tracking
        const { error: sessionError } = await supabase
          .from('agent_sessions')
          .insert({
            session_key: sessionKey,
            agent_name: agentName,
            task_description: task,
            status: 'active',
          });

        if (sessionError) {
          console.error('[AgentWebhook] Failed to create session:', sessionError);
          // Don't fail the webhook if session tracking fails
        } else {
          console.log(`[AgentWebhook] Created session record for ${agentName}`);
        }

        // Create new task in in_progress status
        const title = task.length > 100 ? task.substring(0, 97) + '...' : task;
        
        const { data: newTask, error: createError } = await supabase
          .from('agent_tasks')
          .insert({
            title,
            description: task,
            status: 'in_progress',
            assigned_agent: agentName,
            created_by: 'orchestrator',
            priority: 'medium',
            // Store session key in a way we can look it up later
            // We'll use a metadata approach via description or a comment
          })
          .select()
          .single();

        if (createError) {
          console.error('Error creating task:', createError);
          return NextResponse.json({ error: 'Failed to create task' }, { status: 500 });
        }

        // Add a system comment with the session key for tracking
        await supabase.from('task_comments').insert({
          task_id: newTask.id,
          author: 'system',
          content: `🤖 Task started by ${agentName}\nSession: ${sessionKey}`,
        });

        // Log to agent_activity for Agent Communications feed
        await supabase.from('agent_activity').insert({
          session_key: sessionKey,
          agent_name: agentName,
          agent_emoji: getAgentEmoji(agentName),
          message_preview: `Starting: ${task.substring(0, 100)}${task.length > 100 ? '...' : ''}`,
          full_message: task,
          message_type: 'spawn',
        });

        return NextResponse.json({ 
          success: true, 
          taskId: newTask.id,
          message: 'Task created' 
        }, { status: 201 });
      }

      case 'progress': {
        // Update session's updated_at (keeps it "active" in the 5-minute window)
        await supabase
          .from('agent_sessions')
          .update({ 
            updated_at: new Date().toISOString(),
            task_description: result || task, // Update task description with progress
          })
          .eq('session_key', sessionKey);

        // Find the task by session key in comments
        const { data: comments } = await supabase
          .from('task_comments')
          .select('task_id')
          .like('content', `%Session: ${sessionKey}%`)
          .limit(1);

        if (!comments || comments.length === 0) {
          return NextResponse.json({ error: 'Task not found for session' }, { status: 404 });
        }

        const taskId = comments[0].task_id;

        // Add progress comment
        await supabase.from('task_comments').insert({
          task_id: taskId,
          author: agentName,
          content: `📊 Progress: ${result || task}`,
        });

        console.log(`[AgentWebhook] Updated progress for ${agentName}`);

        return NextResponse.json({ success: true, taskId, message: 'Progress recorded' });
      }

      case 'complete': {
        // Update agent session to completed
        await supabase
          .from('agent_sessions')
          .update({ 
            status: 'completed',
            completed_at: new Date().toISOString(),
            result: result || 'Task finished successfully',
          })
          .eq('session_key', sessionKey);

        // Find the task by session key in comments
        const { data: comments } = await supabase
          .from('task_comments')
          .select('task_id')
          .like('content', `%Session: ${sessionKey}%`)
          .limit(1);

        if (!comments || comments.length === 0) {
          return NextResponse.json({ error: 'Task not found for session' }, { status: 404 });
        }

        const taskId = comments[0].task_id;

        // Update task status to review (needs verification before done)
        const { error: updateError } = await supabase
          .from('agent_tasks')
          .update({ status: 'review' })
          .eq('id', taskId);

        if (updateError) {
          console.error('Error updating task:', updateError);
          return NextResponse.json({ error: 'Failed to update task' }, { status: 500 });
        }

        // Add completion comment
        await supabase.from('task_comments').insert({
          task_id: taskId,
          author: agentName,
          content: `✅ Completed: ${result || 'Task finished successfully'}`,
        });

        // Log to agent_activity for Agent Communications feed
        const completionMsg = result || 'Task finished successfully';
        await supabase.from('agent_activity').insert({
          session_key: sessionKey,
          agent_name: agentName,
          agent_emoji: getAgentEmoji(agentName),
          message_preview: `Completed: ${completionMsg.substring(0, 100)}${completionMsg.length > 100 ? '...' : ''}`,
          full_message: completionMsg,
          message_type: 'complete',
        });

        console.log(`[AgentWebhook] Marked session ${sessionKey.substring(0, 8)} as completed`);

        return NextResponse.json({ success: true, taskId, message: 'Task marked for review' });
      }

      case 'error': {
        // Update agent session to error
        await supabase
          .from('agent_sessions')
          .update({ 
            status: 'error',
            completed_at: new Date().toISOString(),
            result: errorMsg || 'Task failed - needs retry',
          })
          .eq('session_key', sessionKey);

        // Find the task by session key in comments
        const { data: comments } = await supabase
          .from('task_comments')
          .select('task_id')
          .like('content', `%Session: ${sessionKey}%`)
          .limit(1);

        if (!comments || comments.length === 0) {
          return NextResponse.json({ error: 'Task not found for session' }, { status: 404 });
        }

        const taskId = comments[0].task_id;

        // Update task status back to inbox (needs retry)
        const { error: updateError } = await supabase
          .from('agent_tasks')
          .update({ status: 'inbox' })
          .eq('id', taskId);

        if (updateError) {
          console.error('Error updating task:', updateError);
          return NextResponse.json({ error: 'Failed to update task' }, { status: 500 });
        }

        // Add error comment
        await supabase.from('task_comments').insert({
          task_id: taskId,
          author: agentName,
          content: `❌ Error: ${errorMsg || 'Task failed - needs retry'}`,
        });

        // Log to agent_activity for Agent Communications feed
        const errorMessage = errorMsg || 'Task failed - needs retry';
        await supabase.from('agent_activity').insert({
          session_key: sessionKey,
          agent_name: agentName,
          agent_emoji: getAgentEmoji(agentName),
          message_preview: `Error: ${errorMessage.substring(0, 100)}${errorMessage.length > 100 ? '...' : ''}`,
          full_message: errorMessage,
          message_type: 'error',
        });

        console.log(`[AgentWebhook] Marked session ${sessionKey.substring(0, 8)} as error`);

        return NextResponse.json({ success: true, taskId, message: 'Task marked for retry' });
      }

      default:
        return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }
  } catch (e) {
    console.error('Agent webhook error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// GET endpoint for health check
export async function GET() {
  return NextResponse.json({ 
    status: 'ok', 
    endpoint: 'agent-webhook',
    actions: ['spawn', 'progress', 'complete', 'error']
  });
}
