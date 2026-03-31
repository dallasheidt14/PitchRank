import { google } from 'googleapis';

function getCredentials() {
  const json = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!json) {
    throw new Error('GOOGLE_SERVICE_ACCOUNT_JSON environment variable is not set');
  }
  return JSON.parse(json);
}

function getAuth() {
  const credentials = getCredentials();
  return new google.auth.JWT({
    email: credentials.client_email,
    key: credentials.private_key,
    scopes: [
      'https://www.googleapis.com/auth/webmasters.readonly',
      'https://www.googleapis.com/auth/analytics.readonly',
    ],
  });
}

export function getSearchConsoleClient() {
  return google.webmasters({ version: 'v3', auth: getAuth() });
}

export function getAnalyticsDataClient() {
  return google.analyticsdata({ version: 'v1beta', auth: getAuth() });
}
