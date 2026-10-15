import { describe, expect, it } from 'vitest';
import { readFileSync } from 'fs';
import path from 'path';
import ts from 'typescript';
import { componentSources } from '@/test/component-sources';

const ROOT = path.resolve(__dirname, '..');

function tsxFiles(): string[] {
  return componentSources().map((rel) => path.join(ROOT, rel));
}

function tagName(node: ts.Node): string | null {
  if (ts.isJsxElement(node)) return node.openingElement.tagName.getText();
  if (ts.isJsxSelfClosingElement(node)) return node.tagName.getText();
  return null;
}

function hasAsChild(node: ts.JsxElement): boolean {
  return node.openingElement.attributes.properties.some((p) => ts.isJsxAttribute(p) && p.name.getText() === 'asChild');
}

function descendantTags(node: ts.Node, names: Set<string>, out: ts.Node[] = []): ts.Node[] {
  ts.forEachChild(node, (child) => {
    const name = tagName(child);
    if (name && names.has(name)) out.push(child);
    descendantTags(child, names, out);
  });
  return out;
}

const ANCHORS = new Set(['Link', 'a']);
const BUTTONS = new Set(['Button', 'button']);

function findNestedInteractive(file: string, source: string): string[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const hits: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxElement(node)) {
      const name = tagName(node)!;
      const inner = ANCHORS.has(name)
        ? descendantTags(node, BUTTONS)
        : BUTTONS.has(name) && !hasAsChild(node)
          ? descendantTags(node, ANCHORS)
          : [];
      for (const n of inner) {
        const line = sf.getLineAndCharacterOfPosition(n.getStart()).line + 1;
        hits.push(`${path.relative(ROOT, file)}:${line} <${tagName(n)}> inside <${name}>`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return hits;
}

// Nesting the two is invalid HTML and gives keyboard users two tab stops for one action.
// Write `<Button asChild><Link …>…</Link></Button>` instead.
describe('no link wraps a button, and no button wraps a link', () => {
  it('finds none across app/ and components/', () => {
    const files = tsxFiles();
    expect(files.length).toBeGreaterThan(150);
    const hits = files.flatMap((f) => findNestedInteractive(f, readFileSync(f, 'utf-8')));
    expect(hits).toEqual([]);
  });

  it('detects the single-line, multi-line-attribute and nested forms', () => {
    const sample = `
      const a = <Link href="/"><Button>x</Button></Link>;
      const b = (
        <Link
          href="/"
          onClick={() => track()}
        >
          <Button size="sm">x</Button>
        </Link>
      );
      const c = <Link href="/"><div><Button>x</Button></div></Link>;
      const d = <Button><Link href="/">x</Link></Button>;
      const ok = <Button asChild><Link href="/">x</Link></Button>;
    `;
    expect(findNestedInteractive(path.join(ROOT, 'sample.tsx'), sample)).toHaveLength(4);
  });
});
