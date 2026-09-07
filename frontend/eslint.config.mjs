import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },
  {
    // Middleware is the only place that hand-builds the outgoing response, so a
    // redirect started from scratch there drops the session cookies @supabase/ssr
    // just refreshed and signs the user out. The exits that legitimately predate
    // the refresh opt out inline.
    files: ['middleware.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.object.name='NextResponse'][callee.property.name=/^(redirect|rewrite)$/]",
          message:
            'Use redirectWithSession() so the refreshed Supabase cookies survive the redirect. If this exit runs before the session refresh, opt out with an eslint-disable-next-line saying so.',
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    '.next/**',
    'out/**',
    'build/**',
    'next-env.d.ts',
  ]),
]);

export default eslintConfig;
