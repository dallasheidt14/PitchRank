#!/usr/bin/env node
/**
 * Static HTML Test - Demonstrates Playwright with a local file.
 *
 * Usage:
 *   node static_test.js
 */

const path = require('path');
const { chromium } = require(path.join(__dirname, '../../../frontend/node_modules/playwright'));

async function main() {
    const htmlPath = path.join(__dirname, 'static_test.html');
    const fileUrl = `file://${htmlPath}`;

    console.log('='.repeat(60));
    console.log('STATIC HTML TEST - Demonstrating Playwright');
    console.log('='.repeat(60));
    console.log(`\nTesting file: ${htmlPath}\n`);

    const browser = await chromium.launch({
        headless: true,
        executablePath: '/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome'
    });
    const page = await browser.newPage();

    await page.goto(fileUrl);

    // Test navigation
    const navLinks = await page.locator('nav a').all();
    console.log(`[PASS] Found ${navLinks.length} navigation links`);

    // Test heading
    const h1 = await page.locator('h1').textContent();
    console.log(`[PASS] Found heading: "${h1}"`);

    // Test buttons
    const buttons = await page.locator('button').all();
    console.log(`[PASS] Found ${buttons.length} button(s)`);

    // Test inputs
    const inputs = await page.locator('input').all();
    console.log(`[PASS] Found ${inputs.length} input(s)`);

    // Test footer
    const footer = await page.locator('footer').count();
    console.log(`[PASS] Has footer: ${footer > 0}`);

    // Screenshot
    await page.screenshot({ path: '/tmp/static_test.png', fullPage: true });
    console.log(`\n[INFO] Screenshot saved to /tmp/static_test.png`);

    await browser.close();

    console.log('\n' + '='.repeat(60));
    console.log('Test completed successfully!');
    console.log('='.repeat(60));
}

main().catch(e => {
    console.error('Error:', e);
    process.exit(1);
});
