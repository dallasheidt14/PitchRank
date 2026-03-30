'use client';

import { useState } from 'react';
import { TeamSelector } from '@/components/TeamSelector';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { RankingRow } from '@/types/RankingRow';

type FormState = 'idle' | 'loading' | 'success' | 'error';

export function ReportCardForm() {
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [selectedTeam, setSelectedTeam] = useState<RankingRow | null>(null);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('');
  const [formState, setFormState] = useState<FormState>('idle');
  const [errorMessage, setErrorMessage] = useState('');

  const handleTeamChange = (teamId: string | null, team: RankingRow | null) => {
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
          <div className="text-4xl mb-4">⚽</div>
          <h2 className="text-xl font-bold mb-2">Check your inbox!</h2>
          <p className="text-muted-foreground mb-1">
            Your report card for <span className="font-semibold text-foreground">{selectedTeam?.team_name}</span> is on its way.
          </p>
          <p className="text-sm text-muted-foreground">
            Don&apos;t see it? Check your spam folder.
          </p>
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
      <CardContent className="p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <TeamSelector
            label="Find your team"
            value={selectedTeamId}
            onChange={handleTeamChange}
          />

          <div>
            <label htmlFor="report-card-email" className="text-sm font-medium mb-2 block">
              Email address
            </label>
            <Input
              id="report-card-email"
              type="email"
              placeholder="Where should we send it?"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div>
            <label htmlFor="report-card-role" className="text-sm font-medium mb-2 block">
              Your role <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <select
              id="report-card-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">Select...</option>
              <option value="parent">Parent</option>
              <option value="coach">Coach</option>
              <option value="director">Club Director</option>
              <option value="other">Other</option>
            </select>
          </div>

          {formState === 'error' && (
            <p className="text-sm text-destructive">{errorMessage}</p>
          )}

          <Button
            type="submit"
            className="w-full bg-[#0B5345] hover:bg-[#1a6b5c] text-white font-semibold"
            disabled={!selectedTeamId || !email || formState === 'loading'}
          >
            {formState === 'loading' ? 'Generating...' : 'Send My Report Card'}
          </Button>

          <p className="text-xs text-center text-muted-foreground">
            Free. No credit card. Unsubscribe anytime.
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
