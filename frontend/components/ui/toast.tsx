'use client';

import * as React from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface ToastProps {
  id: string;
  title?: string;
  description?: string;
  variant?: 'default' | 'success' | 'error' | 'warning';
  duration?: number;
  onClose?: () => void;
}

const Toast = React.forwardRef<HTMLDivElement, ToastProps & { className?: string }>(
  ({ className, id, title, description, variant = 'default', onClose, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'group pointer-events-auto relative flex w-full items-center justify-between space-x-4 overflow-hidden rounded-md border p-6 pr-8 shadow-lg transition-all',
          {
            'bg-background border-border': variant === 'default',
            'bg-green-50 border-green-200 dark:bg-green-950 dark:border-green-800': variant === 'success',
            'bg-red-50 border-red-200 dark:bg-red-950 dark:border-red-800': variant === 'error',
            'bg-yellow-50 border-yellow-200 dark:bg-yellow-950 dark:border-yellow-800': variant === 'warning',
          },
          className
        )}
        {...props}
      >
        <div className="grid gap-1">
          {title && (
            <div className={cn('text-sm font-semibold', {
              'text-green-900 dark:text-green-100': variant === 'success',
              'text-red-900 dark:text-red-100': variant === 'error',
              'text-yellow-900 dark:text-yellow-100': variant === 'warning',
            })}>
              {title}
            </div>
          )}
          {description && (
            <div className={cn('text-sm opacity-90', {
              'text-green-800 dark:text-green-200': variant === 'success',
              'text-red-800 dark:text-red-200': variant === 'error',
              'text-yellow-800 dark:text-yellow-200': variant === 'warning',
            })}>
              {description}
            </div>
          )}
        </div>
        <button
          className={cn('absolute right-2 top-2 rounded-md p-2 min-w-[44px] min-h-[44px] flex items-center justify-center opacity-0 transition-opacity hover:opacity-100 focus:opacity-100 focus:outline-none group-hover:opacity-100', {
            'text-green-600 dark:text-green-400': variant === 'success',
            'text-red-600 dark:text-red-400': variant === 'error',
            'text-yellow-600 dark:text-yellow-400': variant === 'warning',
          })}
          onClick={onClose}
        >
          <X className="h-5 w-5" />
        </button>
      </div>
    );
  }
);
Toast.displayName = 'Toast';

export { Toast };

