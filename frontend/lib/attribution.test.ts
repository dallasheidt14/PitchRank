import { beforeEach, describe, expect, it } from 'vitest';
import {
  attributionFromParams,
  captureLandingAttribution,
  mergeAttribution,
  readAttribution,
  recordClickAttribution,
  sanitizeAttribution,
} from './attribution';

beforeEach(() => {
  window.sessionStorage.clear();
});

describe('sanitizeAttribution', () => {
  it('keeps only the six known keys, as strings capped at 100 characters without control characters', () => {
    expect(
      sanitizeAttribution({
        campaign: 'black-friday-2026',
        source: 'ban\u0000ner\n',
        utm_source: 'x'.repeat(150),
        utm_medium: 42,
        utm_term: 'dropped',
        utm_content: '',
      })
    ).toEqual({ campaign: 'black-friday-2026', source: 'banner', utm_source: 'x'.repeat(100) });
  });

  it('answers nothing for something that is not an object', () => {
    expect(sanitizeAttribution('campaign=x')).toEqual({});
    expect(sanitizeAttribution(null)).toEqual({});
  });
});

describe('mergeAttribution', () => {
  it("lets a key in the page's URL win, and fills each key it lacks from the session", () => {
    expect(mergeAttribution({ utm_source: 'page' }, { utm_source: 'stored', utm_medium: 'email' })).toEqual({
      utm_source: 'page',
      utm_medium: 'email',
    });
  });

  it("keeps a landing utm_source under the banner's campaign and source", () => {
    expect(mergeAttribution({ campaign: 'black-friday-2026', source: 'banner' }, { utm_source: 'facebook' })).toEqual({
      campaign: 'black-friday-2026',
      source: 'banner',
      utm_source: 'facebook',
    });
  });
});

describe('session attribution', () => {
  it("stores the landing's campaign and UTM values, but not the paywall's source", () => {
    captureLandingAttribution('?utm_source=facebook&utm_campaign=bf&source=clutch_factor&next=/teams/x');

    expect(readAttribution()).toEqual({ utm_source: 'facebook', utm_campaign: 'bf' });
  });

  it('keeps the first touch of each key for the session', () => {
    captureLandingAttribution('?utm_source=facebook');
    captureLandingAttribution('?utm_source=google&utm_medium=cpc');

    expect(readAttribution()).toEqual({ utm_source: 'facebook', utm_medium: 'cpc' });
  });

  it('overwrites just the keys a banner click records', () => {
    captureLandingAttribution('?utm_source=facebook&campaign=old');
    recordClickAttribution({ campaign: 'black-friday-2026', source: 'banner' });

    expect(readAttribution()).toEqual({ utm_source: 'facebook', campaign: 'black-friday-2026', source: 'banner' });
  });

  it('reads the same keys from a page URL', () => {
    expect(attributionFromParams(new URLSearchParams('campaign=bf&source=banner&gclid=1'))).toEqual({
      campaign: 'bf',
      source: 'banner',
    });
  });
});
