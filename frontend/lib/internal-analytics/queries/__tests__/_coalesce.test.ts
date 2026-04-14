import { describe, it, expect, vi } from 'vitest';
import { coalesce, sortedKeys } from '../_coalesce';

describe('coalesce', () => {
  it('returns the same promise for concurrent same-key calls', async () => {
    const fn = vi.fn(async () => {
      await new Promise((r) => setTimeout(r, 10));
      return 42;
    });
    const [a, b] = await Promise.all([coalesce('k', fn), coalesce('k', fn)]);
    expect(a).toBe(42);
    expect(b).toBe(42);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('does not share between different keys', async () => {
    const fn = vi.fn(async () => 1);
    await Promise.all([coalesce('a', fn), coalesce('b', fn)]);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('releases the slot after rejection so retries are possible', async () => {
    let n = 0;
    const fn = async () => {
      n++;
      if (n === 1) throw new Error('first');
      return 'ok';
    };
    await expect(coalesce('k', fn)).rejects.toThrow('first');
    await expect(coalesce('k', fn)).resolves.toBe('ok');
  });
});

describe('sortedKeys', () => {
  it('produces stable JSON regardless of property insertion order', () => {
    expect(sortedKeys({ b: 1, a: 2 })).toBe(JSON.stringify({ a: 2, b: 1 }));
  });
});
