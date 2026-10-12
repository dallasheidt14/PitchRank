import { describe, expect, it } from 'vitest';
import { genderSlug } from './constants';

describe('genderSlug', () => {
  it('maps codes and slugs in any case to the rankings URL slug', () => {
    expect(genderSlug('F')).toBe('female');
    expect(genderSlug('G')).toBe('female');
    expect(genderSlug('f')).toBe('female');
    expect(genderSlug('girls')).toBe('female');
    expect(genderSlug('Female')).toBe('female');
    expect(genderSlug('M')).toBe('male');
    expect(genderSlug('b')).toBe('male');
    expect(genderSlug('male')).toBe('male');
    expect(genderSlug('Boys')).toBe('male');
  });
  it('returns null for anything else', () => {
    expect(genderSlug('x')).toBeNull();
    expect(genderSlug('')).toBeNull();
    expect(genderSlug(null)).toBeNull();
  });
});
