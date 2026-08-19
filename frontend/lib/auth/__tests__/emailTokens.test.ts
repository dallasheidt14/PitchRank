import { describe, it, expect } from 'vitest';
import { isVerifiableOtpType, safeNextPath } from '../emailTokens';

const BACKSLASH = String.fromCharCode(92);

describe('safeNextPath', () => {
  it('keeps a same-origin path and its query', () => {
    expect(safeNextPath('/watchlist')).toBe('/watchlist');
    expect(safeNextPath('/reset-password?a=1')).toBe('/reset-password?a=1');
  });

  it('rejects a protocol-relative value', () => {
    expect(safeNextPath('//evil.example')).toBe('/rankings');
  });

  it('rejects an absolute URL', () => {
    expect(safeNextPath('https://evil.example')).toBe('/rankings');
  });

  it('rejects a backslash authority, which browsers resolve off-origin', () => {
    expect(safeNextPath(`/${BACKSLASH}evil.example`)).toBe('/rankings');
    expect(safeNextPath(`/${BACKSLASH}/evil.example`)).toBe('/rankings');
  });

  it('rejects dot segments that normalize into an authority', () => {
    for (const raw of [
      '/..//evil.example',
      '/../..//evil.example',
      '/a/..//evil.example',
      '/%2e%2e//evil.example',
      `/%2e%2e/${BACKSLASH}evil.example`,
    ]) {
      expect(safeNextPath(raw)).toBe('/rankings');
    }
  });

  it('never returns a value that reparses to another origin', () => {
    const hostile = [
      '//evil.example',
      'https://evil.example',
      `/${BACKSLASH}evil.example`,
      '/..//evil.example',
      '/%2e%2e//evil.example',
    ];

    for (const raw of hostile) {
      const resolved = new URL(safeNextPath(raw), 'https://www.pitchrank.io');
      expect(resolved.origin).toBe('https://www.pitchrank.io');
    }
  });

  it('falls back for empty, missing, or non-rooted values', () => {
    expect(safeNextPath(null)).toBe('/rankings');
    expect(safeNextPath(undefined)).toBe('/rankings');
    expect(safeNextPath('')).toBe('/rankings');
    expect(safeNextPath('watchlist')).toBe('/rankings');
  });

  it('honors a caller-supplied fallback', () => {
    expect(safeNextPath('//evil.example', '/login')).toBe('/login');
  });
});

describe('isVerifiableOtpType', () => {
  it('accepts every type Supabase verifies from a token hash', () => {
    for (const type of ['email', 'recovery', 'invite', 'email_change', 'signup', 'magiclink']) {
      expect(isVerifiableOtpType(type)).toBe(true);
    }
  });

  it('rejects anything else', () => {
    expect(isVerifiableOtpType('bogus')).toBe(false);
    expect(isVerifiableOtpType('')).toBe(false);
  });
});
