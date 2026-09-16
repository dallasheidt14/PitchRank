/**
 * Internal HTML-to-PDF worker. Receives only local temporary files from Python;
 * it does not navigate to files or URLs and cannot fetch remote resources.
 */
import { readFile, writeFile } from 'node:fs/promises';

const [inputPath, outputPath] = process.argv.slice(2);
let browser;

try {
  if (!inputPath || !outputPath || process.argv.length !== 4) {
    throw new Error('Usage: node render-seeding-pdf.mjs input.html output.pdf');
  }
  let chromium;
  try {
    ({ chromium } = await import('@playwright/test'));
  } catch {
    throw new Error('PDF export needs frontend dependencies. Run npm ci in frontend, then retry.');
  }
  for (const channel of [undefined, 'msedge', 'chrome']) {
    try {
      browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
      break;
    } catch {
      // Prefer an existing bundled browser, then installed Edge/Chrome.
    }
  }
  if (!browser) {
    throw new Error(
      'PDF export needs Chromium, Edge or Chrome. Run npx playwright install chromium in frontend, then retry.'
    );
  }
  const markup = await readFile(inputPath, 'utf8');
  const context = await browser.newContext({ javaScriptEnabled: false, serviceWorkers: 'block' });
  await context.route('**/*', (route) => route.abort());
  const page = await context.newPage();
  await page.setContent(markup, { waitUntil: 'load', timeout: 30000 });
  await page.emulateMedia({ media: 'print' });
  await page.evaluate(() => document.fonts.ready);
  const pdf = await page.pdf({
    format: 'Letter',
    preferCSSPageSize: true,
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate:
      '<div style="width:100%;margin:0 12mm;font:8px Arial;color:#5B6B66;display:flex;justify-content:space-between">' +
      '<span>MatchBalance by PitchRank</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>',
    tagged: true,
  });
  await writeFile(outputPath, pdf);
} catch (error) {
  process.stderr.write((error instanceof Error ? error.message : String(error)) + '\n');
  process.exitCode = 1;
} finally {
  await browser?.close();
}
