import type { Metadata } from 'next';
import Link from 'next/link';
import { ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { AuthCardShell } from '@/components/auth/AuthCardShell';
import { isVerifiableOtpType } from '@/lib/auth/emailTokens';
import { confirmEmailLink } from './actions';
import { SubmitButton } from './SubmitButton';

export const metadata: Metadata = {
  title: 'Confirm your link',
  robots: { index: false, follow: false },
};

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? '') : (value ?? '');
}

// Mail providers fetch every link in a message before the recipient sees it, and
// a Supabase token is single-use. Rendering this page redeems nothing; only the
// POST behind the button calls verifyOtp, and scanners do not submit forms.
export default async function ConfirmPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const tokenHash = first(params.token_hash);
  const type = first(params.type);
  const next = first(params.next);

  if (!tokenHash || !isVerifiableOtpType(type)) {
    return (
      <AuthCardShell>
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl font-bold tracking-tight">Link not valid</CardTitle>
          <CardDescription className="text-base">
            This link is missing information it needs. Request a new one and try again.
          </CardDescription>
        </CardHeader>
        <CardFooter className="flex justify-center">
          <Link href="/forgot-password">
            <Button variant="outline">Request a new link</Button>
          </Link>
        </CardFooter>
      </AuthCardShell>
    );
  }

  const isRecovery = type === 'recovery';

  return (
    <AuthCardShell>
      <CardHeader className="space-y-1 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
          <ShieldCheck className="h-6 w-6 text-primary" />
        </div>
        <CardTitle className="text-2xl font-bold tracking-tight">
          {isRecovery ? 'Set your password' : 'Confirm your email'}
        </CardTitle>
        <CardDescription className="text-base">
          {isRecovery
            ? 'Click below to choose a new password for your account.'
            : 'Click below to finish confirming your email address.'}
        </CardDescription>
      </CardHeader>
      <form action={confirmEmailLink}>
        <CardContent>
          <input type="hidden" name="token_hash" value={tokenHash} />
          <input type="hidden" name="type" value={type} />
          <input type="hidden" name="next" value={next} />
          <p className="text-center text-sm text-muted-foreground">
            This link can only be used once and expires in 24 hours.
          </p>
        </CardContent>
        <CardFooter className="flex flex-col gap-4">
          <SubmitButton
            label={isRecovery ? 'Continue' : 'Confirm email'}
            pendingLabel={isRecovery ? 'Continuing...' : 'Confirming email...'}
          />
        </CardFooter>
      </form>
    </AuthCardShell>
  );
}
