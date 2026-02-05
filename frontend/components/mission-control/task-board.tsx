'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { RefreshCw, Kanban, Wifi, WifiOff } from 'lucide-react';
import { TaskCard } from './task-card';
import { TaskModal } from './task-modal';
import { NewTaskForm } from './new-task-form';
import { createSupabaseBrowserClient } from '@/lib/supabaseBrowserClient';

export type TaskStatus = 'inbox' | 'assigned' | 'in_progress' | 'review' | 'done';

interface Task {
  id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  assigned_agent: string | null;
  created_by: string;
  priority: 'low' | 'medium' | 'high';
  created_at: string;
  updated_at: string;
}

const COLUMNS = [
  { id: 'inbox', title: '📥 Inbox', color: 'bg-slate-100 dark:bg-slate-800' },
  { id: 'assigned', title: '👤 Assigned', color: 'bg-amber-50 dark:bg-amber-950' },
  { id: 'in_progress', title: '🔄 In Progress', color: 'bg-blue-50 dark:bg-blue-950' },
  { id: 'review', title: '👁️ Review', color: 'bg-purple-50 dark:bg-purple-950' },
  { id: 'done', title: '✅ Done', color: 'bg-green-50 dark:bg-green-950' },
] as const;

// Map old statuses to new ones (for backward compatibility)
function normalizeStatus(status: string): TaskStatus {
  if (status === 'todo') {
    return 'inbox'; // Old 'todo' becomes 'inbox'
  }
  if (['inbox', 'assigned', 'in_progress', 'review', 'done'].includes(status)) {
    return status as TaskStatus;
  }
  return 'inbox'; // Default fallback
}

export function TaskBoard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);
  const [isRealtime, setIsRealtime] = useState(false);

  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch('/api/tasks');
      if (res.ok) {
        const data = await res.json();
        // Normalize statuses for all tasks
        const normalizedTasks = (data.tasks || []).map((t: Task) => ({
          ...t,
          status: normalizeStatus(t.status),
        }));
        setTasks(normalizedTasks);
        setError(null);
      } else {
        setError('Failed to load tasks');
      }
    } catch (e) {
      setError('Failed to load tasks');
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch and Supabase Realtime subscription
  useEffect(() => {
    fetchTasks();

    // Set up Supabase Realtime subscription
    const supabase = createSupabaseBrowserClient();
    
    const channel = supabase
      .channel('agent_tasks_changes')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'agent_tasks',
        },
        (payload) => {
          console.log('Realtime update:', payload.eventType, payload);
          
          // Handle different event types
          if (payload.eventType === 'INSERT') {
            const newTask = payload.new as Task;
            setTasks((prev) => [
              { ...newTask, status: normalizeStatus(newTask.status) },
              ...prev,
            ]);
          } else if (payload.eventType === 'UPDATE') {
            const updatedTask = payload.new as Task;
            setTasks((prev) =>
              prev.map((t) =>
                t.id === updatedTask.id
                  ? { ...updatedTask, status: normalizeStatus(updatedTask.status) }
                  : t
              )
            );
            // Also update selected task if open
            setSelectedTask((prev) =>
              prev?.id === updatedTask.id
                ? { ...updatedTask, status: normalizeStatus(updatedTask.status) }
                : prev
            );
          } else if (payload.eventType === 'DELETE') {
            const deletedTask = payload.old as { id: string };
            setTasks((prev) => prev.filter((t) => t.id !== deletedTask.id));
            // Close modal if deleted task was selected
            setSelectedTask((prev) => (prev?.id === deletedTask.id ? null : prev));
            if (selectedTask?.id === deletedTask.id) {
              setModalOpen(false);
            }
          }
        }
      )
      .subscribe((status) => {
        console.log('Realtime subscription status:', status);
        setIsRealtime(status === 'SUBSCRIBED');
      });

    // Cleanup subscription on unmount
    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchTasks, selectedTask?.id]);

  const handleTaskCreated = (task: Task) => {
    // With realtime enabled, the task will arrive via subscription
    // But add it optimistically for immediate feedback
    setTasks((prev) => [{ ...task, status: normalizeStatus(task.status) }, ...prev]);
  };

  const handleTaskUpdate = (updatedTask: Task) => {
    setTasks((prev) =>
      prev.map((t) =>
        t.id === updatedTask.id
          ? { ...updatedTask, status: normalizeStatus(updatedTask.status) }
          : t
      )
    );
    setSelectedTask({ ...updatedTask, status: normalizeStatus(updatedTask.status) });
  };

  const handleTaskDelete = (taskId: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
  };

  const handleDragOver = (e: React.DragEvent, columnId: string) => {
    e.preventDefault();
    setDragOverColumn(columnId);
  };

  const handleDragLeave = () => {
    setDragOverColumn(null);
  };

  const handleDrop = async (e: React.DragEvent, newStatus: TaskStatus) => {
    e.preventDefault();
    setDragOverColumn(null);

    const taskId = e.dataTransfer.getData('taskId');
    if (!taskId) return;

    const task = tasks.find((t) => t.id === taskId);
    if (!task || task.status === newStatus) return;

    // Optimistic update
    setTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, status: newStatus } : t))
    );

    try {
      const res = await fetch(`/api/tasks/${taskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });

      if (!res.ok) {
        // Revert on error
        setTasks((prev) => prev.map((t) => (t.id === taskId ? task : t)));
      }
    } catch (e) {
      // Revert on error
      setTasks((prev) => prev.map((t) => (t.id === taskId ? task : t)));
      console.error('Failed to update task:', e);
    }
  };

  const openTaskModal = (task: Task) => {
    setSelectedTask(task);
    setModalOpen(true);
  };

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <Kanban className="h-5 w-5" />
            Task Board
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-32">
            <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <Kanban className="h-5 w-5" />
            Task Board
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground text-center py-8">
            {error}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Kanban className="h-5 w-5" />
              Task Board
              {isRealtime ? (
                <span title="Real-time updates active">
                  <Wifi className="h-4 w-4 text-green-500" />
                </span>
              ) : (
                <span title="Connecting to real-time...">
                  <WifiOff className="h-4 w-4 text-muted-foreground" />
                </span>
              )}
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant="secondary">{tasks.length} tasks</Badge>
              <NewTaskForm onTaskCreated={handleTaskCreated} />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
            {COLUMNS.map((column) => {
              const columnTasks = tasks.filter((t) => t.status === column.id);
              const isDragOver = dragOverColumn === column.id;

              return (
                <div
                  key={column.id}
                  className={`rounded-lg p-2 min-h-[300px] transition-colors ${column.color} ${
                    isDragOver ? 'ring-2 ring-blue-500 ring-offset-2' : ''
                  }`}
                  onDragOver={(e) => handleDragOver(e, column.id)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, column.id)}
                >
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-medium text-xs">{column.title}</h3>
                    <Badge variant="outline" className="text-xs px-1.5 py-0">
                      {columnTasks.length}
                    </Badge>
                  </div>

                  <div className="space-y-1.5">
                    {columnTasks.length === 0 ? (
                      <div className="text-xs text-muted-foreground text-center py-6 border-2 border-dashed rounded-lg">
                        Drop here
                      </div>
                    ) : (
                      columnTasks.map((task) => (
                        <TaskCard
                          key={task.id}
                          id={task.id}
                          title={task.title}
                          description={task.description}
                          assigned_agent={task.assigned_agent}
                          priority={task.priority}
                          onClick={() => openTaskModal(task)}
                        />
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <TaskModal
        task={selectedTask}
        open={modalOpen}
        onOpenChange={setModalOpen}
        onUpdate={handleTaskUpdate}
        onDelete={handleTaskDelete}
      />
    </>
  );
}
