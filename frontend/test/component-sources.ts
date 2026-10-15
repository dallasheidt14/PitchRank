import { readdirSync, readFileSync } from 'fs';
import path from 'path';

const FRONTEND = path.resolve(__dirname, '..');
const SCAN_DIRS = ['app', 'components'];

/** Every non-test `.tsx` file under `app/` and `components/`, as a frontend-relative path with forward slashes. */
export function componentSources(): string[] {
  return SCAN_DIRS.flatMap((dir) =>
    (readdirSync(path.join(FRONTEND, dir), { recursive: true }) as string[])
      .map((file) => `${dir}/${file.replace(/\\/g, '/')}`)
      .filter((rel) => rel.endsWith('.tsx') && !rel.endsWith('.test.tsx') && !rel.includes('/__tests__/'))
  );
}

/** A source file's text with block comments and whole-line `//` comments removed; a trailing `//` comment survives. */
export function sourceCode(rel: string): string {
  return readFileSync(path.join(FRONTEND, rel), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
}
