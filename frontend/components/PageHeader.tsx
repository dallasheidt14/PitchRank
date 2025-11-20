import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { ArrowLeft } from 'lucide-react';

interface PageHeaderProps {
  title: string;
  description?: string;
  showBackButton?: boolean;
  backHref?: string;
}

export function PageHeader({
  title,
  description,
  showBackButton = false,
  backHref = '/',
}: PageHeaderProps) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div className="flex-1">
        {showBackButton && (
          <Link href={backHref}>
            <Button variant="ghost" size="sm" className="mb-2 -ml-2">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back
            </Button>
          </Link>
        )}
        <h1 className="font-display text-3xl font-bold uppercase tracking-wide">{title}</h1>
        {description && (
          <p className="mt-2 text-muted-foreground">{description}</p>
        )}
      </div>
    </div>
  );
}

