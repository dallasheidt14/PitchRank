import { Card, CardContent } from '@/components/ui/card';

interface BlogContentProps {
  content: React.ReactNode;
}

export function BlogContent({ content }: BlogContentProps) {
  return (
    <Card>
      <CardContent className="pt-6">
        <article className="blog-content">
          {content}
        </article>
      </CardContent>
    </Card>
  );
}
