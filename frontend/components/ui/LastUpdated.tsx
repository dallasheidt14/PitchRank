'use client';

import { Clock } from 'lucide-react';
import { isToday, isYesterday, format, parseISO } from 'date-fns';

interface LastUpdatedProps {
  date: string | null;
  label?: string;
}

/**
 * LastUpdated component - displays day-based relative time
 * Shows "Today", "Yesterday", or the formatted date
 */
export function LastUpdated({ date, label = "Last updated" }: LastUpdatedProps) {
  if (!date) return null;

  try {
    const dateObj = typeof date === 'string' ? parseISO(date) : new Date(date);
    
    let displayText: string;
    if (isToday(dateObj)) {
      displayText = 'Today';
    } else if (isYesterday(dateObj)) {
      displayText = 'Yesterday';
    } else {
      // Show date in readable format (e.g., "Nov 7, 2025")
      displayText = format(dateObj, 'MMM d, yyyy');
    }

    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Clock className="h-3 w-3" />
        <span>{label}: {displayText}</span>
      </div>
    );
  } catch (error) {
    // If date parsing fails, return null
    console.error('Error formatting date:', error);
    return null;
  }
}

