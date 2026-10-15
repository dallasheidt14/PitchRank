// Tailwind's `container` caps a row's width without centring it, so a row missing `mx-auto` sits flush left from
// 640 px up while the header and the rest of the page are centred.
import { describe, expect, it } from 'vitest';
import { componentSources, sourceCode } from '@/test/component-sources';

const CLASS_STRING = /(["'`])([^"'`]*)\1/g;
// The utility itself, not a container query (`@container/...`) or a name that contains the word.
const CONTAINER = /(?:^|\s)container(?:\s|$)/;
const CENTRED = /(?:^|\s)mx-auto(?:\s|$)/;

describe('container rows', () => {
  it('are all centred', () => {
    const rows = componentSources().flatMap((rel) =>
      [...sourceCode(rel).matchAll(CLASS_STRING)]
        .map((match) => match[2])
        .filter((classes) => CONTAINER.test(classes))
        .map((classes) => ({ rel, classes }))
    );

    expect(rows.length).toBeGreaterThan(20); // a pattern that matched nothing would pass the check below
    expect(rows.filter(({ classes }) => !CENTRED.test(classes))).toEqual([]);
  });
});
