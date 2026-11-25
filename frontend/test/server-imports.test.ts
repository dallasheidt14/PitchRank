import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'fs';
import os from 'os';
import path from 'path';
import { describe, expect, it } from 'vitest';

const FRONTEND = path.resolve(__dirname, '..');

/** Next registers a route handler written in TypeScript or JavaScript. */
const ROUTE_FILE = /(^|\/)route\.[jt]sx?$/;
const SOURCE_FILE = /\.[jt]sx?$/;

/**
 * Route handlers compile in Next's RSC layer, where every export of a `'use client'` module is a
 * stub that throws when called. Vitest applies no such transform, so a server route calling a
 * client helper passes every unit test and fails only once deployed. This follows every route
 * handler's imports through the tree and refuses any client module it reaches.
 */
const ROUTE_HANDLERS = (readdirSync(path.join(FRONTEND, 'app'), { recursive: true }) as string[])
  .map((file) => `app/${file.replace(/\\/g, '/')}`)
  .filter((rel) => ROUTE_FILE.test(rel));

/** `import … from`, a side-effect `import '…'` and `export … from`, but not `import type` or `export type`. */
const STATIC_IMPORT = /^\s*(?:import|export)\s+(?!type\b)(?:[^'";]*?\bfrom\s+)?['"]([^'"]+)['"]/gm;
const DYNAMIC_IMPORT = /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g;
const LEADING_COMMENT = /^\s*(?:\/\*[\s\S]*?\*\/|\/\/[^\n]*)/;

function importSpecifiers(source: string): string[] {
  return [...source.matchAll(STATIC_IMPORT), ...source.matchAll(DYNAMIC_IMPORT)].map(([, specifier]) => specifier);
}

function resolveImport(from: string, specifier: string): string | null {
  const base = specifier.startsWith('@/')
    ? path.join(FRONTEND, specifier.slice(2))
    : specifier.startsWith('.')
      ? path.resolve(path.dirname(from), specifier)
      : null;
  if (!base) return null;
  const extensions = ['.ts', '.tsx', '.js', '.jsx'];
  for (const candidate of [
    base,
    ...extensions.map((extension) => `${base}${extension}`),
    ...extensions.map((extension) => path.join(base, `index${extension}`)),
  ]) {
    if (existsSync(candidate) && SOURCE_FILE.test(candidate)) return candidate;
  }
  return null;
}

function firstStatement(source: string): string {
  let rest = source;
  while (LEADING_COMMENT.test(rest)) rest = rest.replace(LEADING_COMMENT, '');
  return rest.trimStart().split('\n')[0];
}

const isClientModule = (file: string) => /^['"]use client['"]/.test(firstStatement(readFileSync(file, 'utf8')));

function reachableModules(entry: string): string[] {
  const seen = new Set<string>();
  const queue = [path.resolve(FRONTEND, entry)];
  while (queue.length) {
    const file = queue.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    for (const specifier of importSpecifiers(readFileSync(file, 'utf8'))) {
      const resolved = resolveImport(file, specifier);
      if (resolved) queue.push(resolved);
    }
  }
  return [...seen];
}

const relative = (file: string) => path.relative(FRONTEND, file).replace(/\\/g, '/');

describe('server code never imports a client module', () => {
  it('finds the route handlers, the sale routes among them', () => {
    expect(ROUTE_HANDLERS).toEqual(
      expect.arrayContaining([
        'app/api/stripe/checkout/route.ts',
        'app/api/stripe/webhook/route.ts',
        'app/api/promotion/route.ts',
      ])
    );
  });

  it.each(ROUTE_HANDLERS)('%s', (entry) => {
    const clientModules = reachableModules(entry).filter(isClientModule).map(relative);

    expect(clientModules).toEqual([]);
  });

  it('notices a client module, so the check above can fail', () => {
    expect(isClientModule(path.join(FRONTEND, 'hooks/useUser.ts'))).toBe(true);
    expect(reachableModules('app/upgrade/page.tsx').map(relative)).toContain('hooks/useUser.ts');
  });

  it('finds a JavaScript route handler, and a client module it reaches written in JavaScript', () => {
    expect(ROUTE_FILE.test('app/api/example/route.js')).toBe(true);
    expect(ROUTE_FILE.test('app/api/example/route.jsx')).toBe(true);
    const dir = mkdtempSync(path.join(os.tmpdir(), 'server-imports-'));
    try {
      writeFileSync(path.join(dir, 'route.js'), "import { helper } from './helper';\nexport const GET = helper;\n");
      writeFileSync(path.join(dir, 'helper.jsx'), "'use client';\nexport const helper = () => null;\n");

      const reached = reachableModules(path.join(dir, 'route.js'));

      expect(reached).toContain(path.join(dir, 'helper.jsx'));
      expect(reached.filter(isClientModule)).toEqual([path.join(dir, 'helper.jsx')]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('follows every form of import, and reads past every leading comment', () => {
    const source = [
      "import { a } from './a';",
      "import './side-effect';",
      'import type { T } from "./types-only";',
      "export { b } from '@/lib/b';",
      "export * from './c';",
      'export type { U } from "./types-only-too";',
      "const lazy = () => import('./d');",
      "export const label = 'not a module';",
    ].join('\n');

    expect(importSpecifiers(source).sort()).toEqual(['./a', './c', './d', './side-effect', '@/lib/b']);
    expect(firstStatement("/** one */\n// two\n/* three */\n'use client';\n")).toBe("'use client';");
  });
});
