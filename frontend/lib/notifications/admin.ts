/**
 * Admin notifications via Telegram.
 *
 * Requires env vars:
 *   TELEGRAM_BOT_TOKEN     – Bot token from @BotFather
 *   TELEGRAM_ADMIN_CHAT_ID – Your personal chat ID (get from @userinfobot)
 */

/**
 * Send a Telegram message to the admin. Fails silently so it never
 * blocks webhook processing — alerts are best-effort.
 */
export async function notifyAdmin(message: string): Promise<void> {
  const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN?.trim();
  const CHAT_ID = process.env.TELEGRAM_ADMIN_CHAT_ID?.trim();

  if (!BOT_TOKEN || !CHAT_ID) {
    console.warn('Admin notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID not set');
    return;
  }

  try {
    const res = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: CHAT_ID,
        text: message,
        parse_mode: 'HTML',
      }),
    });

    if (!res.ok) {
      const body = await res.text();
      console.error(`Telegram notification failed (${res.status}): ${body}`);
    }
  } catch (err) {
    console.error('Telegram notification error:', err);
  }
}
