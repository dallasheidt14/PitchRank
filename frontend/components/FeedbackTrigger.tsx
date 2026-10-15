'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { HelpCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { FeedbackModal } from './FeedbackModal';

const HIDDEN_PREFIXES = ['/embed', '/login', '/signup'];

/** `icon` is a "?" button; `menu` is a full-width labelled row. */
export function FeedbackTrigger({ variant = 'icon' }: { variant?: 'icon' | 'menu' }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  if (pathname && HIDDEN_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'))) {
    return null;
  }

  return (
    <>
      {variant === 'menu' ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          data-testid="feedback-trigger-menu"
          className="w-full text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent hover:bg-accent/10 py-3 px-2 rounded-md min-h-[44px] flex items-center gap-2"
        >
          <HelpCircle className="h-4 w-4" />
          Feedback or questions
        </button>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Feedback or questions"
          title="Feedback/Questions"
          onClick={() => setOpen(true)}
          data-testid="feedback-trigger"
        >
          <HelpCircle className="h-5 w-5" />
        </Button>
      )}
      {/* The phone menu stays open while this dialog is up: closing the menu would unmount this state. */}
      <FeedbackModal open={open} onOpenChange={setOpen} />
    </>
  );
}
