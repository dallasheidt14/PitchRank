import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Card, CardContent } from '@/components/ui/card';

interface BlogContentProps {
  content: React.ReactNode | string;
}

const REMARK_PLUGINS = [remarkGfm];

const MARKDOWN_STYLES = [
  'markdown-body space-y-4',
  '[&_h2]:text-2xl [&_h2]:font-bold [&_h2]:mt-8 [&_h2]:mb-4',
  '[&_h3]:text-xl [&_h3]:font-semibold [&_h3]:mt-6 [&_h3]:mb-3',
  '[&_p]:text-muted-foreground [&_p]:leading-relaxed',
  '[&_ul]:list-disc [&_ul]:pl-6 [&_ul]:space-y-1',
  '[&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:space-y-1',
  '[&_li]:text-muted-foreground',
  '[&_strong]:text-foreground',
  '[&_a]:text-primary [&_a]:underline',
  '[&_table]:w-full [&_th]:text-left [&_th]:p-2 [&_th]:border-b [&_th]:font-semibold',
  '[&_td]:p-2 [&_td]:border-b',
  '[&_blockquote]:border-l-4 [&_blockquote]:border-primary/30 [&_blockquote]:pl-4',
  '[&_blockquote]:italic [&_blockquote]:text-muted-foreground',
].join(' ');

export function BlogContent({ content }: BlogContentProps) {
  return (
    <Card>
      <CardContent className="pt-6">
        <article className="blog-content">
          {typeof content === 'string' ? (
            <div className={MARKDOWN_STYLES}>
              <Markdown remarkPlugins={REMARK_PLUGINS}>{content}</Markdown>
            </div>
          ) : (
            content
          )}
        </article>
      </CardContent>
    </Card>
  );
}
