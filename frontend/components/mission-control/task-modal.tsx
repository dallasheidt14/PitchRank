'use client';

import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Send, Clock, User, Trash2 } from 'lucide-react';

// Agent list for mentions and assignment
const AGENTS = ['cleany', 'watchy', 'compy', 'scrappy', 'ranky', 'movy', 'codey', 'socialy', 'orchestrator'];
const AGENT_EMOJIS: Record<string, string> = {
  cleany: '🧹',
  watchy: '👀',
  compy: '🧠',
  scrappy: '🕷️',
  ranky: '📊',
  movy: '🎬',
  codey: '💻',
  socialy: '📱',
  orchestrator: '🎛️',
  'D H': '👤',
};

interface Comment {
  id: string;
  task_id: string;
  author: string;
  content: string;
  created_at: string;
}

interface Task {
  id: string;
  title: string;
  description: string | null;
  status: 'todo' | 'in_progress' | 'done';
  assigned_agent: string | null;
  created_by: string;
  priority: 'low' | 'medium' | 'high';
  created_at: string;
  updated_at: string;
}

interface TaskModalProps {
  task: Task | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdate: (task: Task) => void;
  onDelete: (taskId: string) => void;
}

// Parse @mentions in text and return JSX with highlighted mentions
function parseMentions(text: string): React.ReactNode {
  const parts = text.split(/(@\w+)/g);
  return parts.map((part, i) => {
    if (part.startsWith('@')) {
      const agentName = part.slice(1).toLowerCase();
      const emoji = AGENT_EMOJIS[agentName] || '🤖';
      return (
        <Badge
          key={i}
          variant="secondary"
          className="mx-0.5 text-xs font-normal"
        >
          {emoji} {part}
        </Badge>
      );
    }
    return part;
  });
}

function CommentItem({ comment }: { comment: Comment }) {
  const time = new Date(comment.created_at);
  const timeStr = time.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
  const emoji = AGENT_EMOJIS[comment.author.toLowerCase()] || '👤';

  return (
    <div className="flex gap-3 py-3 border-b last:border-0">
      <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center text-lg flex-shrink-0">
        {emoji}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="font-medium text-sm capitalize">{comment.author}</span>
          <span className="text-xs text-muted-foreground">{timeStr}</span>
        </div>
        <div className="text-sm text-foreground/90 whitespace-pre-wrap">
          {parseMentions(comment.content)}
        </div>
      </div>
    </div>
  );
}

export function TaskModal({ task, open, onOpenChange, onUpdate, onDelete }: TaskModalProps) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loadingComments, setLoadingComments] = useState(false);
  const [newComment, setNewComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<Task['status']>('todo');
  const [assignedAgent, setAssignedAgent] = useState<string>('');
  const [priority, setPriority] = useState<Task['priority']>('medium');

  // Load comments when modal opens
  useEffect(() => {
    if (open && task) {
      setStatus(task.status);
      setAssignedAgent(task.assigned_agent || '');
      setPriority(task.priority);
      fetchComments();
    }
  }, [open, task]);

  const fetchComments = async () => {
    if (!task) return;
    setLoadingComments(true);
    try {
      const res = await fetch(`/api/tasks/${task.id}/comments`);
      if (res.ok) {
        const data = await res.json();
        setComments(data.comments || []);
      }
    } catch (e) {
      console.error('Failed to fetch comments:', e);
    } finally {
      setLoadingComments(false);
    }
  };

  const handleAddComment = async () => {
    if (!task || !newComment.trim()) return;
    setSubmitting(true);
    try {
      const res = await fetch(`/api/tasks/${task.id}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author: 'D H', // TODO: Get from auth context
          content: newComment.trim(),
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setComments((prev) => [...prev, data.comment]);
        setNewComment('');
      }
    } catch (e) {
      console.error('Failed to add comment:', e);
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdateTask = async () => {
    if (!task) return;
    try {
      const res = await fetch(`/api/tasks/${task.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status,
          assigned_agent: assignedAgent || null,
          priority,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        onUpdate(data.task);
      }
    } catch (e) {
      console.error('Failed to update task:', e);
    }
  };

  const handleDelete = async () => {
    if (!task || !confirm('Delete this task?')) return;
    try {
      const res = await fetch(`/api/tasks/${task.id}`, { method: 'DELETE' });
      if (res.ok) {
        onDelete(task.id);
        onOpenChange(false);
      }
    } catch (e) {
      console.error('Failed to delete task:', e);
    }
  };

  // Auto-save when status/agent/priority changes
  useEffect(() => {
    if (task && (status !== task.status || assignedAgent !== (task.assigned_agent || '') || priority !== task.priority)) {
      const timeout = setTimeout(handleUpdateTask, 500);
      return () => clearTimeout(timeout);
    }
  }, [status, assignedAgent, priority]);

  if (!task) return null;

  const createdAt = new Date(task.created_at).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-xl">{task.title}</DialogTitle>
          <DialogDescription className="flex items-center gap-2 text-xs">
            <Clock className="h-3 w-3" />
            Created {createdAt} by {task.created_by}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          {/* Description */}
          {task.description && (
            <div className="p-3 bg-muted/50 rounded-lg">
              <p className="text-sm whitespace-pre-wrap">{task.description}</p>
            </div>
          )}

          {/* Controls */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-medium mb-1 block">Status</label>
              <Select value={status} onValueChange={(v) => setStatus(v as Task['status'])}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="todo">📋 To Do</SelectItem>
                  <SelectItem value="in_progress">🔄 In Progress</SelectItem>
                  <SelectItem value="done">✅ Done</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="text-xs font-medium mb-1 block">Assignee</label>
              <Select value={assignedAgent} onValueChange={setAssignedAgent}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Unassigned" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">Unassigned</SelectItem>
                  {AGENTS.map((agent) => (
                    <SelectItem key={agent} value={agent}>
                      {AGENT_EMOJIS[agent]} {agent}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="text-xs font-medium mb-1 block">Priority</label>
              <Select value={priority} onValueChange={(v) => setPriority(v as Task['priority'])}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">🟢 Low</SelectItem>
                  <SelectItem value="medium">🟡 Medium</SelectItem>
                  <SelectItem value="high">🔴 High</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Comments */}
          <div className="border-t pt-4">
            <h3 className="font-medium text-sm mb-3 flex items-center gap-2">
              <User className="h-4 w-4" />
              Comments ({comments.length})
            </h3>

            {loadingComments ? (
              <div className="text-sm text-muted-foreground text-center py-4">
                Loading comments...
              </div>
            ) : comments.length === 0 ? (
              <div className="text-sm text-muted-foreground text-center py-4">
                No comments yet
              </div>
            ) : (
              <div className="space-y-0 max-h-60 overflow-y-auto">
                {comments.map((comment) => (
                  <CommentItem key={comment.id} comment={comment} />
                ))}
              </div>
            )}

            {/* New comment input */}
            <div className="mt-4 flex gap-2">
              <Textarea
                placeholder="Add a comment... (use @agent to mention)"
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                className="min-h-[60px] text-sm"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    handleAddComment();
                  }
                }}
              />
              <Button
                size="sm"
                onClick={handleAddComment}
                disabled={!newComment.trim() || submitting}
                className="self-end"
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t pt-4 flex justify-between">
          <Button variant="destructive" size="sm" onClick={handleDelete}>
            <Trash2 className="h-4 w-4 mr-1" />
            Delete
          </Button>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
