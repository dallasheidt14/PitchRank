import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { BlogContent } from './BlogContent';

const MARKDOWN_TABLE = ['| Level | Who plays |', '| --- | --- |', '| ECNL | Elite clubs |'].join('\n');

function render(content: string) {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(<BlogContent content={content} />);
  return host;
}

describe('BlogContent', () => {
  it('wraps a markdown table in a box that scrolls sideways', () => {
    const table = render(MARKDOWN_TABLE).querySelector('table')!;

    expect(table.parentElement!.className.split(/\s+/)).toContain('overflow-x-auto');
  });

  it('lets a keyboard user focus the scrolling box', () => {
    const table = render(MARKDOWN_TABLE).querySelector('table')!;

    expect(table.parentElement!.getAttribute('tabindex')).toBe('0');
  });

  it('renders the header and body cells', () => {
    const host = render(MARKDOWN_TABLE);

    expect(host.querySelector('th')!.textContent).toBe('Level');
    expect(host.querySelector('td')!.textContent).toBe('ECNL');
  });
});
