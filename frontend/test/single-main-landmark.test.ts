// The root layout owns the page's only main landmark; a page that adds its own nests a second one inside it.
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'fs';
import path from 'path';

const FRONTEND = path.resolve(__dirname, '..');
const SCAN_DIRS = ['app', 'components'];

function sources(): string[] {
  return SCAN_DIRS.flatMap((dir) =>
    (readdirSync(path.join(FRONTEND, dir), { recursive: true }) as string[])
      .map((file) => `${dir}/${file.replace(/\\/g, '/')}`)
      .filter((rel) => rel.endsWith('.tsx') && !rel.endsWith('.test.tsx') && !rel.includes('/__tests__/'))
  );
}

// The ways this codebase opens a main landmark: the element itself, created by name, or a role prop.
const MAIN_LANDMARK = /<main[\s>]|createElement\(\s*['"]main['"]|role=\{?\s*['"]main['"]/;

describe('main landmark', () => {
  it('is rendered by the root layout and nowhere else', () => {
    const files = sources();
    const code = (rel: string) =>
      readFileSync(path.join(FRONTEND, rel), 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '');

    expect(files.length).toBeGreaterThan(150); // a walk that found nothing would pass the check below
    expect(files.filter((rel) => MAIN_LANDMARK.test(code(rel)))).toEqual(['app/layout.tsx']);
  });
});
