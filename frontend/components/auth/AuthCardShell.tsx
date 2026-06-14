import type { ComponentProps, ReactNode } from 'react';
import { Card } from '@/components/ui/card';

/**
 * Shared outer shell for the auth pages (login, signup, forgot/reset password):
 * a full-height centered layout wrapping an elevated max-w-md card. Children
 * supply the CardHeader / CardContent / CardFooter.
 */
export function AuthCardShell({
  children,
  ...cardProps
}: { children: ReactNode } & Omit<ComponentProps<typeof Card>, 'children'>) {
  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4 py-12">
      <Card variant="elevated" {...cardProps} className="w-full max-w-md">
        {children}
      </Card>
    </div>
  );
}
