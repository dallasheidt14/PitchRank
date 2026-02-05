'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { RefreshCw, Kanban } from 'lucide-react';
import { TaskCard } from './task-card';
import { TaskModal } from './task-modal';
import { NewTaskForm } from './new-task-form';

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

const COLUMNS = [
  { id: 'todo', title: '📋 To Do', color: 'bg-slate-100 dark:bg-slate-800' },
  { id: 'in_progress', title: '🔄 In Progress', color: 'bg-blue-50 dark:bg-blue-950' },
  { id: 'done', title: '✅ Done', color: 'bg-green-50 dark:bg-green-950' },
] as const;

export function TaskBoard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch('/api/tasks');
      if (res.ok) {
        const data = await res.json();
        setTasks(data.tasks || []);
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

  useEffect(() => {
    fetchTasks();
    // Refresh every 30 seconds
    const interval = setInterval(fetchTasks, 30000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

  const handleTaskCreated = (task: Task) => {
    setTasks((prev) => [task, ...prev]);
  };

  const handleTaskUpdate = (updatedTask: Task) => {
    setTasks((prev) =>
      prev.map((t) => (t.id === updatedTask.id ? updatedTask : t))
    );
    setSelectedTask(updatedTask);
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

  const handleDrop = async (e: React.DragEvent, newStatus: Task['status']) => {
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
        setTasks((prev) =>
          prev.map((t) => (t.id === taskId ? task : t))
        );
      }
    } catch (e) {
      // Revert on error
      setTasks((prev) =>
        prev.map((t) => (t.id === taskId ? task : t))
      );
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
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant="secondary">{tasks.length} tasks</Badge>
              <NewTaskForm onTaskCreated={handleTaskCreated} />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {COLUMNS.map((column) => {
              const columnTasks = tasks.filter((t) => t.status === column.id);
              const isDragOver = dragOverColumn === column.id;

              return (
                <div
                  key={column.id}
                  className={`rounded-lg p-3 min-h-[300px] transition-colors ${column.color} ${
                    isDragOver ? 'ring-2 ring-blue-500 ring-offset-2' : ''
                  }`}
                  onDragOver={(e) => handleDragOver(e, column.id)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, column.id as Task['status'])}
                >
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-medium text-sm">{column.title}</h3>
                    <Badge variant="outline" className="text-xs">
                      {columnTasks.length}
                    </Badge>
                  </div>

                  <div className="space-y-2">
                    {columnTasks.length === 0 ? (
                      <div className="text-xs text-muted-foreground text-center py-8 border-2 border-dashed rounded-lg">
                        Drop tasks here
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
