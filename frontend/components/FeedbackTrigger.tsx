'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { HelpCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { FeedbackModal } from './FeedbackModal';

const HIDDEN_PREFIXES = ['/embed', '/login', '/signup'];

export function FeedbackTrigger() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  if (pathname && HIDDEN_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'))) {
    return null;
  }

  return (
    <>
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
      <FeedbackModal open={open} onOpenChange={setOpen} />
    </>
  );
}
