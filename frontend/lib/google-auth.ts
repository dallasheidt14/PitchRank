import 'server-only';
import { google } from 'googleapis';
import type { JWT } from 'google-auth-library';

let _auth: JWT | null = null;

function getAuth(): JWT {
  if (_auth) return _auth;

  const json = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!json) {
    throw new Error('GOOGLE_SERVICE_ACCOUNT_JSON environment variable is not set');
  }

  const credentials = JSON.parse(json);
  _auth = new google.auth.JWT({
    email: credentials.client_email,
    key: credentials.private_key,
    scopes: [
      'https://www.googleapis.com/auth/webmasters.readonly',
      'https://www.googleapis.com/auth/analytics.readonly',
    ],
  });

  return _auth;
}

export function getSearchConsoleClient() {
  return google.webmasters({ version: 'v3', auth: getAuth() });
}

export function getAnalyticsDataClient() {
  return google.analyticsdata({ version: 'v1beta', auth: getAuth() });
}
