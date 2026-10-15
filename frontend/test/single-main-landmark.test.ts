// The root layout owns the page's only main landmark; a page that adds its own nests a second one inside it.
import { describe, expect, it } from 'vitest';
import { componentSources, sourceCode } from '@/test/component-sources';

// The ways this codebase opens a main landmark: the element itself, created by name, or a role prop.
const MAIN_LANDMARK = /<main[\s>]|createElement\(\s*['"]main['"]|role=\{?\s*['"]main['"]/;

describe('main landmark', () => {
  it('is rendered by the root layout and nowhere else', () => {
    const files = componentSources();

    expect(files.length).toBeGreaterThan(150); // a walk that found nothing would pass the check below
    expect(files.filter((rel) => MAIN_LANDMARK.test(sourceCode(rel)))).toEqual(['app/layout.tsx']);
  });
});
