import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const { mockUseFormStatus } = vi.hoisted(() => ({ mockUseFormStatus: vi.fn() }));

vi.mock('react-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-dom')>()),
  useFormStatus: mockUseFormStatus,
}));

import { SubmitButton } from '../SubmitButton';

describe('SubmitButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('disables itself while the redemption is in flight', () => {
    mockUseFormStatus.mockReturnValue({ pending: true });

    const markup = renderToStaticMarkup(<SubmitButton label="Continue" pendingLabel="Continuing..." />);

    // Match the attribute, not the `disabled:` Tailwind variants in className.
    expect(markup).toMatch(/<button[^>]*\sdisabled=""/);
    expect(markup).toContain('Continuing...');
  });

  it('is enabled and shows the action label when idle', () => {
    mockUseFormStatus.mockReturnValue({ pending: false });

    const markup = renderToStaticMarkup(<SubmitButton label="Continue" pendingLabel="Continuing..." />);

    expect(markup).not.toMatch(/<button[^>]*\sdisabled=""/);
    expect(markup).toContain('Continue');
  });
});
