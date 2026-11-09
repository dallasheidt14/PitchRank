import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { mockCreate, mockFire, mockDefaultFire } = vi.hoisted(() => ({
  mockCreate: vi.fn(),
  mockFire: vi.fn(),
  mockDefaultFire: vi.fn(),
}));

vi.mock('canvas-confetti', () => ({
  default: Object.assign(mockDefaultFire, { create: mockCreate }),
}));

import { launchConfetti } from './confetti';

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  mockCreate.mockReturnValue(mockFire);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('launchConfetti', () => {
  it("never starts the library's worker, which the site's CSP refuses", () => {
    launchConfetti();
    vi.advanceTimersByTime(250);

    expect(mockCreate).toHaveBeenCalledWith(undefined, expect.objectContaining({ useWorker: false }));
    expect(mockDefaultFire).not.toHaveBeenCalled();
  });

  it('fires one burst, then two from the sides', () => {
    launchConfetti();
    expect(mockFire).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(250);
    expect(mockFire).toHaveBeenCalledTimes(3);
  });
});
