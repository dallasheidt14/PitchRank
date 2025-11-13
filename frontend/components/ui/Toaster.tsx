'use client';

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Toast } from './toast';
import type { ToastProps } from './toast';

export interface ToastData extends ToastProps {
  id: string;
}

let toastIdCounter = 0;
const toasts: ToastData[] = [];
const listeners: Set<() => void> = new Set();

function notify() {
  listeners.forEach((listener) => listener());
}

export function toast(props: Omit<ToastData, 'id'>) {
  const id = `toast-${++toastIdCounter}`;
  const toastData: ToastData = {
    ...props,
    id,
  };

  toasts.push(toastData);
  notify();

  // Auto-remove after duration
  const duration = props.duration ?? 5000;
  if (duration > 0) {
    setTimeout(() => {
      dismiss(id);
    }, duration);
  }

  return id;
}

export function dismiss(id: string) {
  const index = toasts.findIndex((t) => t.id === id);
  if (index > -1) {
    toasts.splice(index, 1);
    notify();
  }
}

export function Toaster() {
  const [mounted, setMounted] = useState(false);
  const [, setToasts] = useState<ToastData[]>([]);

  useEffect(() => {
    setMounted(true);
    const updateToasts = () => {
      setToasts([...toasts]);
    };
    listeners.add(updateToasts);
    return () => {
      listeners.delete(updateToasts);
    };
  }, []);

  if (!mounted) return null;

  return createPortal(
    <div className="fixed bottom-0 right-0 z-[100] flex max-h-screen w-full flex-col-reverse p-4 sm:bottom-0 sm:right-0 sm:top-auto sm:flex-col md:max-w-[420px]">
      {toasts.map((toastData) => (
        <Toast
          key={toastData.id}
          {...toastData}
          onClose={() => dismiss(toastData.id)}
        />
      ))}
    </div>,
    document.body
  );
}

