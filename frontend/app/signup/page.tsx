"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClientSupabase } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Loader2, Mail, Lock, CheckCircle2, AlertTriangle, RefreshCw } from "lucide-react";

/**
 * Detect if a Supabase auth error is specifically about email delivery failure.
 * When email sending fails, the user account is still created in Supabase —
 * only the confirmation email failed to deliver.
 */
function isEmailSendingError(message: string): boolean {
  const lower = message.toLowerCase();
  return (
    (lower.includes("sending") && (lower.includes("email") || lower.includes("mail"))) ||
    (lower.includes("email") && lower.includes("rate limit")) ||
    lower.includes("confirmation mail") ||
    (lower.includes("smtp") && lower.includes("error"))
  );
}

export default function SignupPage() {
  const router = useRouter();
  const supabase = useMemo(() => createClientSupabase(), []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSuccess, setIsSuccess] = useState(false);
  const [emailSendFailed, setEmailSendFailed] = useState(false);
  const [isResending, setIsResending] = useState(false);
  const [resendMessage, setResendMessage] = useState<string | null>(null);

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validate passwords match
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    // Validate password strength
    if (password.length < 6) {
      setError("Password must be at least 6 characters long.");
      return;
    }

    setIsLoading(true);

    try {
      const { data, error: signUpError } = await supabase.auth.signUp({
        email: email.trim().toLowerCase(),
        password,
        options: {
          // Redirect to rankings page (accessible to all users)
          // New users can explore rankings and upgrade if desired
          emailRedirectTo: `${window.location.origin}/auth/callback?next=/rankings`,
        },
      });

      if (signUpError) {
        // When Supabase fails to send the confirmation email, the user account
        // is still created. Show the success screen with a note about the email
        // issue and a resend button instead of a confusing raw error.
        if (isEmailSendingError(signUpError.message)) {
          setEmailSendFailed(true);
          setIsSuccess(true);
          return;
        }
        throw signUpError;
      }

      // Check if email confirmation is required
      if (data.user && !data.session) {
        // Email confirmation required
        setIsSuccess(true);
      } else if (data.session) {
        // Auto-confirmed, redirect to rankings (accessible to all users)
        router.push("/rankings");
        router.refresh();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Signup failed. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleResendConfirmation = async () => {
    setIsResending(true);
    setResendMessage(null);

    try {
      const { error: resendError } = await supabase.auth.resend({
        type: "signup",
        email: email.trim().toLowerCase(),
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback?next=/rankings`,
        },
      });

      if (resendError) {
        setResendMessage("Unable to resend email. Please try again in a few minutes.");
      } else {
        setResendMessage("Confirmation email sent! Check your inbox.");
        setEmailSendFailed(false);
      }
    } catch {
      setResendMessage("Unable to resend email. Please try again in a few minutes.");
    } finally {
      setIsResending(false);
    }
  };

  if (isSuccess) {
    return (
      <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4 py-12">
        <Card data-testid="signup-success-card" className="w-full max-w-md" variant="elevated">
          <CardHeader className="space-y-1 text-center">
            <div className={`mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full ${emailSendFailed ? "bg-yellow-500/10" : "bg-green-500/10"}`}>
              {emailSendFailed ? (
                <AlertTriangle className="h-6 w-6 text-yellow-600" />
              ) : (
                <CheckCircle2 className="h-6 w-6 text-green-600" />
              )}
            </div>
            <CardTitle className="text-2xl font-bold tracking-tight">
              {emailSendFailed ? "Account created" : "Check your email"}
            </CardTitle>
            <CardDescription className="text-base">
              {emailSendFailed ? (
                <>
                  Your account has been created, but we had trouble sending the
                  confirmation email to{" "}
                  <span className="font-medium text-foreground">{email}</span>
                </>
              ) : (
                <>
                  We&apos;ve sent you a confirmation link to{" "}
                  <span className="font-medium text-foreground">{email}</span>
                </>
              )}
            </CardDescription>
          </CardHeader>
          <CardContent className="text-center space-y-3">
            {emailSendFailed ? (
              <>
                <p className="text-sm text-muted-foreground">
                  Click below to resend the confirmation email, or try again in
                  a few minutes.
                </p>
                <Button
                  variant="outline"
                  onClick={handleResendConfirmation}
                  disabled={isResending}
                  className="mt-2"
                >
                  {isResending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Sending...
                    </>
                  ) : (
                    <>
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Resend confirmation email
                    </>
                  )}
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Click the link in the email to activate your account and start
                tracking your favorite teams.
              </p>
            )}
            {resendMessage && (
              <p className={`text-sm ${resendMessage.includes("sent!") ? "text-green-600" : "text-muted-foreground"}`}>
                {resendMessage}
              </p>
            )}
          </CardContent>
          <CardFooter className="flex justify-center">
            <Link href="/login">
              <Button variant="outline">Back to login</Button>
            </Link>
          </CardFooter>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4 py-12">
      <Card data-testid="signup-card" className="w-full max-w-md" variant="elevated">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl font-bold tracking-tight">
            Create an account
          </CardTitle>
          <CardDescription>
            Sign up for PitchRank to save your favorite teams and track their
            rankings
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSignup}>
          <CardContent className="space-y-4">
            {error && (
              <div data-testid="signup-error" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="pl-10"
                  required
                  autoComplete="email"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="password"
                  type="password"
                  placeholder="At least 6 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pl-10"
                  required
                  minLength={6}
                  autoComplete="new-password"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Confirm Password</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder="Confirm your password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="pl-10"
                  required
                  minLength={6}
                  autoComplete="new-password"
                />
              </div>
            </div>

            <p className="text-xs text-muted-foreground">
              By creating an account, you agree to PitchRank&apos;s{' '}
              <Link href="/terms-of-service" className="text-primary underline-offset-4 hover:underline">
                Terms of Service
              </Link>{' '}
              and{' '}
              <Link href="/privacy-policy" className="text-primary underline-offset-4 hover:underline">
                Privacy Policy
              </Link>.
            </p>
          </CardContent>
          <CardFooter className="flex flex-col gap-4">
            <Button data-testid="signup-submit" type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating account...
                </>
              ) : (
                "Create account"
              )}
            </Button>

            <p className="text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link
                href="/login"
                className="font-medium text-primary underline-offset-4 hover:underline"
              >
                Sign in
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
