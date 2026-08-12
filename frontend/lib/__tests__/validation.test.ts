import { describe, it, expect } from 'vitest';

import { suggestEmailCorrection } from '../validation';

describe('suggestEmailCorrection', () => {
  it('corrects the two typo domains that stranded real signups', () => {
    expect(suggestEmailCorrection('jessevirginpdr@gmai.com')).toBe('jessevirginpdr@gmail.com');
    expect(suggestEmailCorrection('someone@gmail.con')).toBe('someone@gmail.com');
  });

  it('corrects common misspellings across the major providers', () => {
    expect(suggestEmailCorrection('a@gmial.com')).toBe('a@gmail.com');
    expect(suggestEmailCorrection('a@yaho.com')).toBe('a@yahoo.com');
    expect(suggestEmailCorrection('a@hotmial.com')).toBe('a@hotmail.com');
    expect(suggestEmailCorrection('a@outlok.com')).toBe('a@outlook.com');
    expect(suggestEmailCorrection('a@iclould.com')).toBe('a@icloud.com');
  });

  it('leaves correctly spelled provider domains alone', () => {
    expect(suggestEmailCorrection('a@gmail.com')).toBeNull();
    expect(suggestEmailCorrection('a@yahoo.com')).toBeNull();
    expect(suggestEmailCorrection('a@icloud.com')).toBeNull();
  });

  it('never flags the unusual-but-real domains our users actually sign up with', () => {
    expect(suggestEmailCorrection('a@students.cobbk12.org')).toBeNull();
    expect(suggestEmailCorrection('a@worcesterschools.net')).toBeNull();
    expect(suggestEmailCorrection('a@rpsnj.us')).toBeNull();
    expect(suggestEmailCorrection('a@novanthealth.org')).toBeNull();
    expect(suggestEmailCorrection('a@liquid-innovations.biz')).toBeNull();
    expect(suggestEmailCorrection('a@yahoo.co.uk')).toBeNull();
  });

  it('is case- and whitespace-insensitive', () => {
    expect(suggestEmailCorrection('  Someone@GMAI.com  ')).toBe('someone@gmail.com');
  });

  it('returns null for input that is not a single address', () => {
    expect(suggestEmailCorrection('')).toBeNull();
    expect(suggestEmailCorrection('gmai.com')).toBeNull();
    expect(suggestEmailCorrection('@gmai.com')).toBeNull();
    expect(suggestEmailCorrection('a@b@gmai.com')).toBeNull();
  });
});
