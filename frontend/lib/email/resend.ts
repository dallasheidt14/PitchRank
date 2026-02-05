import { Resend } from 'resend';

// Initialize Resend client (will be undefined if API key is not set)
export const resend = process.env.RESEND_API_KEY
  ? new Resend(process.env.RESEND_API_KEY)
  : null;
