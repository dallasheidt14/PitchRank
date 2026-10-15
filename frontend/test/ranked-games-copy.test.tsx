// The copy that states the games threshold reads MIN_RANKED_GAMES, so it moves with the engine instead of drifting.
import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// No copy would hard-code 37, so a literal left in place of the constant cannot pass.
vi.mock('@/lib/constants', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/constants')>()),
  MIN_RANKED_GAMES: 37,
}));

import { MethodologySection } from '@/components/MethodologySection';
import { BlogFAQSchema } from '@/components/BlogFAQSchema';
import { buildCohortFAQ, type CohortModuleData } from '@/lib/cohort-seo';
import { flatten } from '@/test/flatten';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

async function render(element: React.ReactElement) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(element));
  return container;
}

/** The Methodology FAQ markup as it ships. happy-dom decodes entities in a script's text, which crawlers never do. */
function shippedFaq() {
  const schema = flatten(MethodologySection()).find((el) => el.type === BlogFAQSchema)!;
  return JSON.parse(
    BlogFAQSchema(schema.props as Parameters<typeof BlogFAQSchema>[0]).props.dangerouslySetInnerHTML.__html
  );
}

describe('games-threshold copy', () => {
  it('states the threshold on the Methodology page in both places it comes up', async () => {
    const text = (await render(React.createElement(MethodologySection))).textContent!.replace(/\s+/g, ' ');

    expect(text).toContain('Teams need at least 37 verified games in the last 12 months before appearing');
    expect(text).toContain('We require at least 37 verified games in the last 12 months before a team appears');
  });

  it('states it in the FAQ structured data', () => {
    const answer = shippedFaq().mainEntity.find((q: { name: string }) => q.name.startsWith('How accurate are rankings'))
      .acceptedAnswer.text;

    expect(answer).toContain('require at least 37 verified games in the last 12 months');
  });

  // FAQ structured data must match the answers visitors can read, so both come from one list.
  it('marks up exactly the questions and answers the Methodology page shows', async () => {
    const page = await render(React.createElement(MethodologySection));
    const shown = Array.from(page.querySelectorAll('h4'))
      .map((h) => [h.textContent, h.nextElementSibling?.textContent])
      .filter(([question]) => question?.endsWith('?'));

    expect(
      shippedFaq().mainEntity.map((q: { name: string; acceptedAnswer: { text: string } }) => [
        q.name,
        q.acceptedAnswer.text,
      ])
    ).toEqual(shown);
    expect(shown).toHaveLength(8);
  });

  it("states it in every board's FAQ", () => {
    const faq = buildCohortFAQ({
      totalTeams: 120,
      locationText: 'Arizona',
      ageGroupDisplay: 'U13',
      genderLabel: 'boys',
      isNational: false,
    } as CohortModuleData);

    expect(faq.find((item) => item.question.includes('rankings update'))!.answer).toContain(
      'A team needs 37 games in the last 12 months to get a rank.'
    );
  });
});
