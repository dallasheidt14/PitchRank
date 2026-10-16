'use client';

import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GLOBAL_SEARCH_INPUT_IDS } from '@/components/GlobalSearch';

/** Puts the cursor in the header search shown at this width (lg is 64rem). */
export function FindYourTeamButton() {
  const focusSearch = () => {
    const isDesktop = window.matchMedia('(min-width: 64rem)').matches;
    document.getElementById(isDesktop ? GLOBAL_SEARCH_INPUT_IDS.desktop : GLOBAL_SEARCH_INPUT_IDS.mobile)?.focus();
  };

  return (
    <Button
      type="button"
      data-testid="cta-find-team"
      size="lg"
      variant="secondary"
      onClick={focusSearch}
      className="font-semibold uppercase tracking-wide"
    >
      <Search aria-hidden="true" />
      Find your team
    </Button>
  );
}
