'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useUser } from '@/hooks/useUser';
import { MAX_FEEDBACK_LENGTH, MIN_FEEDBACK_LENGTH } from '@/lib/constants';
import { MIN_FEEDBACK_DWELL_MS } from '@/lib/feedbackDwell';
import type { FeedbackCategory as Category } from '@/lib/email';

const CATEGORY_OPTIONS: Array<{ value: Category; label: string }> = [
  { value: 'cant-find-team', label: "I can't find my team" },
  { value: 'rankings-wrong', label: 'Rankings look wrong' },
  { value: 'wrong-games', label: 'Wrong games attached to a team' },
  { value: 'bug', label: 'Bug or broken page' },
  { value: 'other', label: 'Other' },
];

const PLACEHOLDERS: Record<Category, string> = {
  'cant-find-team': 'Club name, age group, gender, state — anything that helps us find them.',
  'rankings-wrong': 'Which team, and what looks off about their ranking?',
  'wrong-games': "Which team's game list looks wrong, and which game(s)?",
  bug: 'What did you click, and what happened vs what you expected?',
  other: "Tell us what's on your mind.",
};

const TEXTAREA_CLASSES =
  'flex w-full min-h-[120px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';

interface FeedbackModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialCategory?: Category;
  initialMessage?: string;
}

type Status = 'idle' | 'submitting' | 'success' | 'error' | 'rate_limited';

/**
 * Inner form is mounted with a fresh `key` on each open and on each pathname
 * change, so all local state (category, message, email, status) resets via
 * remount instead of via setState-in-effect.
 */
function FeedbackForm({
  pathname,
  hasUser,
  userLoading,
  onClose,
  initialCategory,
  initialMessage,
}: {
  pathname: string;
  hasUser: boolean;
  userLoading: boolean;
  onClose: () => void;
  initialCategory?: Category;
  initialMessage?: string;
}) {
  const [category, setCategory] = useState<Category | ''>(initialCategory ?? '');
  const [message, setMessage] = useState(initialMessage ?? '');
  const [email, setEmail] = useState('');
  const [website, setWebsite] = useState(''); // honeypot
  const [status, setStatus] = useState<Status>('idle');
  const openedAtRef = useRef<string>(new Date().toISOString());
  const closedRef = useRef(false);

  // StrictMode remounts with the same refs, so clear what the previous cleanup set.
  useEffect(() => {
    closedRef.current = false;
    return () => {
      closedRef.current = true;
    };
  }, []);

  // Auto-close 4s after success — this is a legitimate external sync (timer).
  useEffect(() => {
    if (status !== 'success') return;
    const t = setTimeout(onClose, 4000);
    return () => clearTimeout(t);
  }, [status, onClose]);

  const canSubmit = useMemo(
    () => category !== '' && message.trim().length >= MIN_FEEDBACK_LENGTH && message.length <= MAX_FEEDBACK_LENGTH,
    [category, message]
  );

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || status === 'submitting') return;
    setStatus('submitting');
    // The route silently drops a report sent inside the dwell window, and a prefilled form can be sent at once.
    const dwellLeft = MIN_FEEDBACK_DWELL_MS - (Date.now() - Date.parse(openedAtRef.current));
    if (dwellLeft > 0) await new Promise((resolve) => setTimeout(resolve, dwellLeft));
    // A form unmounted during the wait (its dialog closed) withdraws its report.
    if (closedRef.current) return;
    try {
      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category,
          message: message.trim(),
          ...(hasUser ? {} : email.trim() ? { email: email.trim() } : {}),
          ...(website ? { website } : {}),
          context: {
            pathname,
            referrer: typeof document !== 'undefined' ? document.referrer : undefined,
            userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
            viewport: typeof window !== 'undefined' ? { w: window.innerWidth, h: window.innerHeight } : undefined,
            openedAt: openedAtRef.current,
            submittedAt: new Date().toISOString(),
          },
        }),
      });

      if (res.status === 429) {
        setStatus('rate_limited');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }

      setStatus('success');
    } catch {
      setStatus('error');
    }
  };

  const placeholder = category ? PLACEHOLDERS[category] : 'Tell us what you saw…';

  if (status === 'success') {
    return (
      <div
        className="rounded-md border border-green-300 bg-green-50 p-4 text-sm text-green-900"
        role="status"
        aria-live="polite"
      >
        Thanks — we got it.
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {status === 'error' && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900" role="alert">
          Couldn&apos;t send right now. Try again, or email pitchrankio@gmail.com.
        </div>
      )}
      {status === 'rate_limited' && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" role="alert">
          You&apos;ve sent a few already — give it an hour and try again.
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="feedback-category">Category</Label>
        <Select value={category} onValueChange={(v) => setCategory(v as Category)}>
          <SelectTrigger id="feedback-category" data-testid="feedback-category">
            <SelectValue placeholder="Select one…" />
          </SelectTrigger>
          <SelectContent>
            {CATEGORY_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="feedback-message">What&apos;s happening?</Label>
        <textarea
          id="feedback-message"
          data-testid="feedback-message"
          className={TEXTAREA_CLASSES}
          placeholder={placeholder}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={5}
          maxLength={MAX_FEEDBACK_LENGTH}
        />
        <p className="text-xs text-muted-foreground">
          {message.trim().length < MIN_FEEDBACK_LENGTH && `At least ${MIN_FEEDBACK_LENGTH} characters · `}
          {message.trim().length} / {MAX_FEEDBACK_LENGTH}
        </p>
      </div>

      {/* Held back while the user loads: a signed-in user would otherwise see the box appear, then vanish. */}
      {!hasUser && !userLoading && (
        <div className="space-y-1.5">
          <Label htmlFor="feedback-email">
            Email <span className="text-muted-foreground font-normal">(optional)</span>
          </Label>
          <Input
            id="feedback-email"
            data-testid="feedback-email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
          <p className="text-xs text-muted-foreground">
            So we can reply if we have questions. We won&apos;t add you to anything.
          </p>
        </div>
      )}

      {/* Honeypot — must remain hidden and not focusable */}
      <div
        style={{
          position: 'absolute',
          left: '-9999px',
          top: 'auto',
          width: 1,
          height: 1,
          overflow: 'hidden',
        }}
      >
        <label htmlFor="feedback-website">Website</label>
        <input
          id="feedback-website"
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
        />
      </div>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={!canSubmit || status === 'submitting'} data-testid="feedback-submit">
          {status === 'submitting' ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Sending…
            </>
          ) : (
            'Send'
          )}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function FeedbackModal({ open, onOpenChange, initialCategory, initialMessage }: FeedbackModalProps) {
  const pathname = usePathname();
  const { user, isLoading: userLoading } = useUser();

  // Bumps each time the modal transitions to open; combined with pathname,
  // forms a stable key that remounts the inner form (resetting all its state).
  // Uses the "store information from previous renders" pattern with useState
  // (https://react.dev/reference/react/useState#storing-information-from-previous-renders).
  const [prevOpen, setPrevOpen] = useState(open);
  const [openCount, setOpenCount] = useState(0);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) setOpenCount((c) => c + 1);
  }

  const formKey = `${pathname ?? ''}:${openCount}`;

  const onClose = useCallback(() => onOpenChange(false), [onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]" data-testid="feedback-modal">
        <DialogHeader>
          <DialogTitle>Feedback/Questions</DialogTitle>
          <DialogDescription>Tell us what you&apos;re seeing — we read every report.</DialogDescription>
        </DialogHeader>

        <FeedbackForm
          key={formKey}
          pathname={pathname ?? ''}
          hasUser={!!user}
          userLoading={userLoading}
          onClose={onClose}
          initialCategory={initialCategory}
          initialMessage={initialMessage}
        />
      </DialogContent>
    </Dialog>
  );
}
