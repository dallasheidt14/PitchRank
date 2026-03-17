// Re-export the OpenGraph image for Twitter Card
// Next.js requires runtime to be statically defined, not re-exported
export { default, alt, size, contentType } from './opengraph-image';

export const runtime = 'edge';
