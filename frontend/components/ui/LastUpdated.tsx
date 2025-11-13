'use client';

import { Clock } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

interface LastUpdatedProps {
  date: string | null;
  label?: string;
}

/**
 * LastUpdated component - displays relative time since last update
 * Shows "X hours ago" format using date-fns
 */
export function LastUpdated({ date, label = "Last updated" }: LastUpdatedProps) {
  if (!date) return null;

  try {
    const formattedDate = formatDistanceToNow(new Date(date), { 
      addSuffix: true 
    });

    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Clock className="h-3 w-3" />
        <span>{label}: {formattedDate}</span>
      </div>
    );
  } catch (error) {
    // If date parsing fails, return null
    console.error('Error formatting date:', error);
    return null;
  }
}

