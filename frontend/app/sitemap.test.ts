import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import path from 'path';
import sitemap from './sitemap';

describe('public page discovery', () => {
  it('lists /matchbalance in the sitemap', () => {
    const urls = sitemap().map((entry) => entry.url);

    expect(urls.some((url) => url.endsWith('/matchbalance'))).toBe(true);
  });

  it('lists /matchbalance under Core Content in the committed llms.txt', () => {
    // The CI drift gate cannot catch an omitted line: the generator and the
    // committed file would then agree with each other.
    const llms = readFileSync(path.join(__dirname, '..', 'public', 'llms.txt'), 'utf-8');
    const coreContent = llms.split('## Core Content')[1]?.split('\n## ')[0] ?? '';

    expect(coreContent).toMatch(/^- \[MatchBalance\]\(https?:\/\/[^)]+\/matchbalance\): /m);
  });
});
