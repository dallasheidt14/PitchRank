const requests = new Map<string, { count: number; resetAt: number }>();

/**
 * Resolve the client IP for rate-limit keying. On Vercel both x-real-ip and
 * x-forwarded-for are overwritten by the platform with the real client IP
 * (incoming values from external clients are discarded to prevent spoofing),
 * so these headers are safe keys in production.
 */
export function getClientIp(request: Request): string {
  return (
    request.headers.get('x-real-ip')?.trim() ||
    request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ||
    'unknown'
  );
}

/**
 * Best-effort limiter: the Map is per serverless instance, so the cap applies
 * per instance rather than globally. Good enough to blunt bursts and abuse;
 * a shared store would be needed for a hard global limit.
 */
export function checkRateLimit(ip: string, maxRequests = 5, windowMs = 60000): boolean {
  const now = Date.now();
  const entry = requests.get(ip);

  if (!entry || now > entry.resetAt) {
    requests.set(ip, { count: 1, resetAt: now + windowMs });
    return true;
  }

  if (entry.count >= maxRequests) return false;
  entry.count++;
  return true;
}
