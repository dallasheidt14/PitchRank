'use client';

import { useState } from 'react';
import { ScopedTeamSelector, type ScopedTeam } from '@/components/ScopedTeamSelector';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { AGE_GROUP_OPTIONS, US_STATES } from '@/lib/constants';
import { CheckCircle2 } from 'lucide-react';

type FormState = 'idle' | 'loading' | 'success' | 'error';

// Gender values match the teams.gender DB column ('Male' | 'Female'), not the
// single-letter codes used elsewhere — /api/teams/search and the report-card
// API filter directly on this column.
const GENDER_FORM_OPTIONS = [
  { value: 'Male', label: 'Boys' },
  { value: 'Female', label: 'Girls' },
] as const;

export function ReportCardForm() {
  const [ageGroup, setAgeGroup] = useState<string | null>(null);
  const [gender, setGender] = useState<string | null>(null);
  const [stateCode, setStateCode] = useState<string | null>(null);
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [selectedTeam, setSelectedTeam] = useState<ScopedTeam | null>(null);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('');
  const [formState, setFormState] = useState<FormState>('idle');
  const [errorMessage, setErrorMessage] = useState('');

  const filtersComplete = Boolean(ageGroup && gender && stateCode);
  const canSubmit = Boolean(selectedTeamId && email) && formState !== 'loading';

  const handleTeamChange = (teamId: string | null, team: ScopedTeam | null) => {
    setSelectedTeamId(teamId);
    setSelectedTeam(team);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTeamId || !email) return;
    setFormState('loading');
    setErrorMessage('');

    try {
      const res = await fetch('/api/reports/team-card', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          teamId: selectedTeamId,
          email: email.trim(),
          role: role || undefined,
        }),
      });
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
          <h2 className="font-oswald text-2xl font-bold mb-2 tracking-wide">Check your inbox</h2>
          <p className="text-muted-foreground mb-1">
            Your report card for <span className="font-semibold text-foreground">{selectedTeam?.team_name}</span> is on
            its way.
          </p>
          <p className="text-sm text-muted-foreground">Don&apos;t see it within 60 seconds? Check your spam folder.</p>
          <Button
            variant="outline"
            className="mt-6"
            onClick={() => {
              setFormState('idle');
              setSelectedTeamId(null);
              setSelectedTeam(null);
              setEmail('');
              setRole('');
            }}
          >
            Get another report card
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="shadow-xl border-0">
      <CardContent className="p-6 md:p-8">
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Step 1 — Find your team */}
          <div>
            <div className="flex items-baseline gap-2 mb-3">
              <span className="font-oswald text-xs uppercase tracking-widest text-[#0B5345] font-bold">Step 1</span>
              <h3 className="font-oswald text-lg font-bold tracking-wide">Find your team</h3>
            </div>

            <div className="grid grid-cols-3 gap-2 mb-4">
              <div>
                <label htmlFor="rc-age" className="text-xs font-medium mb-1 block text-muted-foreground">
                  Age
                </label>
                <Select value={ageGroup ?? undefined} onValueChange={setAgeGroup}>
                  <SelectTrigger id="rc-age" className="w-full h-10">
                    <SelectValue placeholder="Age" />
                  </SelectTrigger>
                  <SelectContent>
                    {AGE_GROUP_OPTIONS.map((ag) => (
                      <SelectItem key={ag.value} value={ag.value}>
                        {ag.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label htmlFor="rc-gender" className="text-xs font-medium mb-1 block text-muted-foreground">
                  Gender
                </label>
                <Select value={gender ?? undefined} onValueChange={setGender}>
                  <SelectTrigger id="rc-gender" className="w-full h-10">
                    <SelectValue placeholder="Gender" />
                  </SelectTrigger>
                  <SelectContent>
                    {GENDER_FORM_OPTIONS.map((g) => (
                      <SelectItem key={g.value} value={g.value}>
                        {g.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label htmlFor="rc-state" className="text-xs font-medium mb-1 block text-muted-foreground">
                  State
                </label>
                <Select value={stateCode ?? undefined} onValueChange={setStateCode}>
                  <SelectTrigger id="rc-state" className="w-full h-10">
                    <SelectValue placeholder="State" />
                  </SelectTrigger>
                  <SelectContent>
                    {US_STATES.map((s) => (
                      <SelectItem key={s.code} value={s.code}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <ScopedTeamSelector
              ageGroup={ageGroup}
              gender={gender}
              stateCode={stateCode}
              value={selectedTeamId}
              onChange={handleTeamChange}
            />
          </div>

          {/* Step 2 — Where to send it */}
          <div
            className={
              !filtersComplete || !selectedTeamId
                ? 'opacity-40 pointer-events-none transition-opacity'
                : 'transition-opacity'
            }
          >
            <div className="flex items-baseline gap-2 mb-3">
              <span className="font-oswald text-xs uppercase tracking-widest text-[#0B5345] font-bold">Step 2</span>
              <h3 className="font-oswald text-lg font-bold tracking-wide">Where should we send it?</h3>
            </div>

            <div className="space-y-3">
              <div>
                <label htmlFor="rc-email" className="text-xs font-medium mb-1 block text-muted-foreground">
                  Email address
                </label>
                <Input
                  id="rc-email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>

              <div>
                <label htmlFor="rc-role" className="text-xs font-medium mb-1 block text-muted-foreground">
                  I&apos;m a <span className="font-normal">(optional)</span>
                </label>
                <Select value={role} onValueChange={setRole}>
                  <SelectTrigger id="rc-role" className="w-full h-10">
                    <SelectValue placeholder="Select..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="parent">Parent</SelectItem>
                    <SelectItem value="coach">Coach</SelectItem>
                    <SelectItem value="director">Club Director</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {formState === 'error' && (
            <p className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3">
              {errorMessage}
            </p>
          )}

          <div>
            <Button
              type="submit"
              className="w-full bg-[#0B5345] hover:bg-[#1a6b5c] text-white font-semibold h-11 text-base"
              disabled={!canSubmit}
            >
              {formState === 'loading' ? 'Generating your report card…' : 'Send My Report Card'}
            </Button>
            <p className="text-xs text-center text-muted-foreground mt-2">
              Free · No credit card · Unsubscribe anytime
            </p>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
