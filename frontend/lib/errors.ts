/**
 * Centralized error handling utilities
 */

/**
 * Custom application error class
 */
export class AppError extends Error {
  code?: string;
  statusCode?: number;

  constructor(message: string, code?: string, statusCode?: number) {
    super(message);
    this.name = 'AppError';
    this.code = code;
    this.statusCode = statusCode;
  }
}

/**
 * Safely extract error message from unknown error type
 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  // Handle Supabase errors
  if (error && typeof error === 'object' && 'message' in error) {
    return String(error.message);
  }

  // Handle string errors
  if (typeof error === 'string') {
    return error;
  }

  // Fallback for unknown error types
  return 'An unexpected error occurred';
}

/**
 * Check if error is a network/connection error
 */
export function isNetworkError(error: unknown): boolean {
  if (!error) return false;

  // Check for fetch/network error patterns
  if (error instanceof TypeError) {
    const message = error.message.toLowerCase();
    return (
      message.includes('fetch') ||
      message.includes('network') ||
      message.includes('connection') ||
      message.includes('failed to fetch')
    );
  }

  // Check for Supabase network errors
  if (error && typeof error === 'object') {
    const errorObj = error as Record<string, unknown>;
    
    // Check for network-related error codes
    if ('code' in errorObj) {
      const code = String(errorObj.code).toLowerCase();
      if (code.includes('network') || code.includes('connection') || code === 'fetch_error') {
        return true;
      }
    }

    // Check for network-related messages
    if ('message' in errorObj) {
      const message = String(errorObj.message).toLowerCase();
      return (
        message.includes('network') ||
        message.includes('connection') ||
        message.includes('fetch') ||
        message.includes('timeout')
      );
    }
  }

  return false;
}

