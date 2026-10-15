import type { ReactElement } from 'react';

/** Every element in a server component's returned tree, depth first, so tests can find one by type or props. */
export function flatten(node: unknown, out: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    node.forEach((child) => flatten(child, out));
    return out;
  }
  if (!node || typeof node !== 'object' || !('props' in node)) return out;
  const element = node as ReactElement<{ children?: unknown }>;
  out.push(element);
  flatten(element.props?.children, out);
  return out;
}
