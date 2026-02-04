import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Calendar, Clock } from 'lucide-react';
import type { BlogPost } from '@/lib/blog';

interface BlogCardProps {
  post: BlogPost;
}

export function BlogCard({ post }: BlogCardProps) {
  return (
    <Link href={`/blog/${post.slug}`} className="group">
      <Card className="h-full transition-all duration-200 hover:shadow-lg hover:scale-[1.02]">
        <CardHeader>
          <CardTitle className="group-hover:text-primary transition-colors">
            {post.title}
          </CardTitle>
          <CardDescription>{post.excerpt}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <div className="flex items-center gap-1">
              <Calendar className="size-3" />
              <time dateTime={post.date}>
                {new Date(post.date).toLocaleDateString('en-US', {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                })}
              </time>
            </div>
            {post.readingTime && (
              <div className="flex items-center gap-1">
                <Clock className="size-3" />
                <span>{post.readingTime}</span>
              </div>
            )}
          </div>
          {post.tags && post.tags.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              {post.tags.map((tag) => (
                <span
                  key={tag}
                  className="text-xs px-2 py-1 rounded-full bg-primary/10 text-primary font-medium"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
