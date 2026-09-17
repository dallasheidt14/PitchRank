'use client';

import { useRef, useState } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  MATCHBALANCE_LIMITS,
  MATCHBALANCE_REQUEST_LABELS,
  MATCHBALANCE_REQUEST_TYPES,
  type MatchBalanceRequestType,
} from '@/lib/matchbalance';
import { suggestEmailCorrection } from '@/lib/validation';

type FormState = 'idle' | 'loading' | 'success' | 'error';

const LABEL_CLASSES = 'text-xs font-medium mb-1 block text-muted-foreground';

const TEXTAREA_CLASSES =
  'flex w-full min-h-[100px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';

export function MatchBalanceInquiryForm() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [organization, setOrganization] = useState('');
  const [tournamentName, setTournamentName] = useState('');
  const [eventDates, setEventDates] = useState('');
  const [teamCount, setTeamCount] = useState('');
  const [bracketReviewDate, setBracketReviewDate] = useState('');
  const [eventUrl, setEventUrl] = useState('');
  const [requestType, setRequestType] = useState<MatchBalanceRequestType>('sample');
  const [notes, setNotes] = useState('');
  const [website, setWebsite] = useState(''); // honeypot
  const [formState, setFormState] = useState<FormState>('idle');
  const [errorMessage, setErrorMessage] = useState('');
  const openedAtRef = useRef<string>(new Date().toISOString());

  const emailSuggestion = suggestEmailCorrection(email);
  const canSubmit =
    Boolean(name.trim() && email.trim() && organization.trim() && tournamentName.trim() && eventDates.trim()) &&
    formState !== 'loading';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setFormState('loading');
    setErrorMessage('');

    try {
      const res = await fetch('/api/matchbalance-inquiry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          organization: organization.trim(),
          tournamentName: tournamentName.trim(),
          eventDates: eventDates.trim(),
          ...(teamCount.trim() ? { teamCount: Number(teamCount) } : {}),
          ...(bracketReviewDate ? { bracketReviewDate } : {}),
          ...(eventUrl.trim() ? { eventUrl: eventUrl.trim() } : {}),
          requestType,
          ...(notes.trim() ? { notes: notes.trim() } : {}),
          ...(website ? { website } : {}),
          openedAt: openedAtRef.current,
          submittedAt: new Date().toISOString(),
        }),
      });

      if (res.status === 429) {
        setFormState('error');
        setErrorMessage('Too many requests, try again in an hour.');
        return;
      }

      const data = await res.json();

      if (!res.ok) {
        setFormState('error');
        setErrorMessage(data.error || 'Something went wrong. Please try again.');
        return;
      }

      setFormState('success');
    } catch {
      setFormState('error');
      setErrorMessage('Network error. Please check your connection and try again.');
    }
  };

  if (formState === 'success') {
    return (
      <Card className="shadow-xl border-0">
        <CardContent className="p-8 text-center">
          <CheckCircle2 className="w-12 h-12 text-[#0B5345] mx-auto mb-3" />
          <h2 className="font-oswald text-2xl font-bold mb-2 tracking-wide">Request received</h2>
          <p className="text-muted-foreground">
            Thanks. We&apos;ll reply within one business day. If you have the accepted-team list already, reply to the
            confirmation email with it attached.
          </p>
          <Button
            variant="outline"
            className="mt-6"
            onClick={() => {
              setFormState('idle');
              setName('');
              setEmail('');
              setOrganization('');
              setTournamentName('');
              setEventDates('');
              setTeamCount('');
              setBracketReviewDate('');
              setEventUrl('');
              setRequestType('sample');
              setNotes('');
              setWebsite('');
              openedAtRef.current = new Date().toISOString();
            }}
          >
            Send another request
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="shadow-xl border-0">
      <CardContent className="p-6 md:p-8">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="mb-name" className={LABEL_CLASSES}>
                Your name
              </label>
              <Input
                id="mb-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={MATCHBALANCE_LIMITS.name}
                autoComplete="name"
                required
              />
            </div>

            <div>
              <label htmlFor="mb-email" className={LABEL_CLASSES}>
                Email
              </label>
              <Input
                id="mb-email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={MATCHBALANCE_LIMITS.email}
                autoComplete="email"
                required
              />
              {emailSuggestion && (
                <p data-testid="matchbalance-email-suggestion" className="mt-1 text-xs text-muted-foreground">
                  Did you mean{' '}
                  <button
                    type="button"
                    onClick={() => setEmail(emailSuggestion)}
                    className="font-medium text-primary underline-offset-4 hover:underline"
                  >
                    {emailSuggestion}
                  </button>
                  ?
                </p>
              )}
            </div>
          </div>

          <div>
            <label htmlFor="mb-organization" className={LABEL_CLASSES}>
              Organization
            </label>
            <Input
              id="mb-organization"
              placeholder="Club, league or event operator"
              value={organization}
              onChange={(e) => setOrganization(e.target.value)}
              maxLength={MATCHBALANCE_LIMITS.organization}
              autoComplete="organization"
              required
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="mb-tournament" className={LABEL_CLASSES}>
                Tournament name
              </label>
              <Input
                id="mb-tournament"
                value={tournamentName}
                onChange={(e) => setTournamentName(e.target.value)}
                maxLength={MATCHBALANCE_LIMITS.tournamentName}
                required
              />
            </div>

            <div>
              <label htmlFor="mb-dates" className={LABEL_CLASSES}>
                Event dates
              </label>
              <Input
                id="mb-dates"
                placeholder="e.g. Sep 5–7, 2026"
                value={eventDates}
                onChange={(e) => setEventDates(e.target.value)}
                maxLength={MATCHBALANCE_LIMITS.eventDates}
                required
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="mb-team-count" className={LABEL_CLASSES}>
                Approximate number of teams <span className="font-normal">(optional)</span>
              </label>
              <Input
                id="mb-team-count"
                type="number"
                inputMode="numeric"
                min={0}
                max={MATCHBALANCE_LIMITS.teamCount}
                step={1}
                value={teamCount}
                onChange={(e) => setTeamCount(e.target.value)}
              />
            </div>

            <div>
              <label htmlFor="mb-bracket-review" className={LABEL_CLASSES}>
                Bracket review date <span className="font-normal">(optional)</span>
              </label>
              <Input
                id="mb-bracket-review"
                type="date"
                value={bracketReviewDate}
                onChange={(e) => setBracketReviewDate(e.target.value)}
              />
            </div>
          </div>

          <div>
            <label htmlFor="mb-event-url" className={LABEL_CLASSES}>
              Event link <span className="font-normal">(optional)</span>
            </label>
            <Input
              id="mb-event-url"
              type="url"
              placeholder="https://"
              value={eventUrl}
              onChange={(e) => setEventUrl(e.target.value)}
              maxLength={MATCHBALANCE_LIMITS.eventUrl}
            />
          </div>

          <fieldset>
            <legend className={LABEL_CLASSES}>What do you need?</legend>
            <div className="flex flex-col gap-2 sm:flex-row sm:gap-6">
              {MATCHBALANCE_REQUEST_TYPES.map((type) => (
                <label key={type} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="radio"
                    name="requestType"
                    value={type}
                    checked={requestType === type}
                    onChange={() => setRequestType(type)}
                    className="h-4 w-4 accent-[#0B5345]"
                  />
                  {MATCHBALANCE_REQUEST_LABELS[type]}
                </label>
              ))}
            </div>
          </fieldset>

          <div>
            <label htmlFor="mb-notes" className={LABEL_CLASSES}>
              Anything else <span className="font-normal">(optional)</span>
            </label>
            <textarea
              id="mb-notes"
              className={TEXTAREA_CLASSES}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              maxLength={MATCHBALANCE_LIMITS.notes}
            />
          </div>

          {/* Honeypot — must remain hidden and not focusable. aria-hidden keeps screen
              readers from offering it, since a filled honeypot silently drops the lead. */}
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: '-9999px',
              top: 'auto',
              width: 1,
              height: 1,
              overflow: 'hidden',
            }}
          >
            <label htmlFor="mb-website">Website</label>
            <input
              id="mb-website"
              name="website"
              type="text"
              tabIndex={-1}
              autoComplete="off"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
            />
          </div>

          {formState === 'error' && (
            <p
              role="alert"
              className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3"
            >
              {errorMessage}
            </p>
          )}

          <div>
            <Button
              type="submit"
              className="w-full bg-[#0B5345] hover:bg-[#1a6b5c] text-white font-semibold h-11 text-base"
              disabled={!canSubmit}
            >
              {formState === 'loading' ? 'Sending…' : 'Send my request'}
            </Button>
            <p className="text-xs text-center text-muted-foreground mt-2">
              No payment details · We reply within one business day
            </p>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
