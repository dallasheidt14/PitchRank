#!/usr/bin/env node
/**
 * PitchRank Frontend Audit - Comprehensive testing for PitchRank app.
 *
 * Usage:
 *   node pitchrank_audit.js [--base-url URL] [--verbose]
 *
 *   # With server running:
 *   cd frontend && npm run dev &
 *   node tests/frontend/examples/pitchrank_audit.js
 */

const path = require('path');
// Use playwright from frontend node_modules
const { chromium } = require(path.join(__dirname, '../../../frontend/node_modules/playwright'));

const BASE_URL = process.argv.find(arg => arg.startsWith('--base-url='))?.split('=')[1] || 'http://localhost:3000';
const VERBOSE = process.argv.includes('--verbose') || process.argv.includes('-v');

let passed = 0;
let failed = 0;
const errors = [];

function log(msg) {
    if (VERBOSE) console.log(`    ${msg}`);
}

function test(name, condition, errorMsg = '') {
    if (condition) {
        passed++;
        console.log(`  [PASS] ${name}`);
    } else {
        failed++;
        console.log(`  [FAIL] ${name}`);
        if (errorMsg) {
            console.log(`         ${errorMsg}`);
            errors.push({ name, error: errorMsg });
        }
    }
}

async function auditHomePage(page) {
    console.log('\n--- Home Page ---');

    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState('networkidle');

    test('Has navigation', await page.locator('nav').count() > 0);
    test('Has main heading', await page.locator('h1').count() > 0);
    test('Has footer', await page.locator('footer').count() > 0);

    const navLinks = await page.locator('nav a').all();
    test('Navigation has links', navLinks.length > 0);
    log(`Found ${navLinks.length} navigation links`);

    await page.screenshot({ path: '/tmp/audit_home.png', fullPage: true });
}

async function auditRankingsPage(page) {
    console.log('\n--- Rankings Page ---');

    await page.goto(`${BASE_URL}/rankings`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const hasTable = await page.locator('table').count() > 0;
    const hasList = await page.locator('[class*="ranking"], [class*="list"]').count() > 0;
    test('Has rankings display', hasTable || hasList);

    const filters = await page.locator('select, [role="combobox"], [class*="filter"]').all();
    test('Has filter controls', filters.length > 0);
    log(`Found ${filters.length} filter controls`);

    const teamLinks = await page.locator('a[href*="/teams/"]').all();
    test('Shows team links', teamLinks.length > 0);
    log(`Found ${teamLinks.length} team links`);

    await page.screenshot({ path: '/tmp/audit_rankings.png', fullPage: true });
}

async function auditTeamsPage(page) {
    console.log('\n--- Teams Page ---');

    await page.goto(`${BASE_URL}/teams`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const searchInput = await page.locator('input[type="search"], input[placeholder*="earch"], input[name*="search"]');
    test('Has search input', await searchInput.count() > 0);

    const teamCards = await page.locator('[class*="team"], [class*="card"], a[href*="/teams/"]').all();
    test('Shows team entries', teamCards.length > 0);
    log(`Found ${teamCards.length} team entries`);

    await page.screenshot({ path: '/tmp/audit_teams.png', fullPage: true });
}

async function auditLoginPage(page) {
    console.log('\n--- Login Page ---');

    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    const emailInput = await page.locator('input[type="email"], input[name="email"], input[placeholder*="mail"]');
    test('Has email input', await emailInput.count() > 0);

    const passwordInput = await page.locator('input[type="password"]');
    test('Has password input', await passwordInput.count() > 0);

    const submitBtn = await page.locator('button[type="submit"], button:has-text("Login"), button:has-text("Sign")');
    test('Has submit button', await submitBtn.count() > 0);

    const signupLink = await page.locator('a[href*="signup"], a:has-text("Sign up"), a:has-text("Register")');
    test('Has signup link', await signupLink.count() > 0);

    await page.screenshot({ path: '/tmp/audit_login.png', fullPage: true });
}

async function auditMethodologyPage(page) {
    console.log('\n--- Methodology Page ---');

    await page.goto(`${BASE_URL}/methodology`);
    await page.waitForLoadState('networkidle');

    const headings = await page.locator('h1, h2').all();
    test('Has headings', headings.length > 0);

    const paragraphs = await page.locator('p').all();
    test('Has explanatory content', paragraphs.length > 0);

    await page.screenshot({ path: '/tmp/audit_methodology.png', fullPage: true });
}

async function auditNavigation(page) {
    console.log('\n--- Navigation Tests ---');

    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState('networkidle');

    const rankingsLink = page.locator('a[href*="ranking"]').first();
    if (await rankingsLink.count() > 0) {
        await rankingsLink.click();
        await page.waitForLoadState('networkidle');
        test('Rankings link works', page.url().includes('/ranking'));
    } else {
        test('Rankings link exists', false, 'No rankings link found');
    }

    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState('networkidle');

    const loginLink = page.locator('a[href*="login"]').first();
    if (await loginLink.count() > 0) {
        await loginLink.click();
        await page.waitForLoadState('networkidle');
        test('Login link works', page.url().includes('/login'));
    } else {
        test('Login link exists', false, 'No login link found');
    }
}

async function auditMobileResponsiveness(page) {
    console.log('\n--- Mobile Responsiveness ---');

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState('networkidle');

    const mobileMenu = await page.locator('[class*="mobile"], [class*="hamburger"], button[aria-label*="menu"], [class*="menu-toggle"]');
    const hasMobileMenu = await mobileMenu.count() > 0;

    const nav = page.locator('nav');
    const navVisible = await nav.count() > 0 ? await nav.isVisible() : false;

    test('Has mobile layout', hasMobileMenu || navVisible);

    await page.screenshot({ path: '/tmp/audit_mobile.png', fullPage: true });
    await page.setViewportSize({ width: 1920, height: 1080 });
}

async function auditConsoleErrors(page) {
    console.log('\n--- Console Error Check ---');

    const consoleErrors = [];

    page.on('console', msg => {
        if (msg.type() === 'error') {
            consoleErrors.push(msg.text());
        }
    });

    page.on('pageerror', error => {
        consoleErrors.push(error.toString());
    });

    const pagesToCheck = ['/', '/rankings', '/teams', '/methodology'];

    for (const path of pagesToCheck) {
        try {
            await page.goto(`${BASE_URL}${path}`);
            await page.waitForLoadState('networkidle');
            await page.waitForTimeout(1000);
        } catch (e) {
            consoleErrors.push(`Navigation error on ${path}: ${e.message}`);
        }
    }

    test('No JavaScript errors', consoleErrors.length === 0,
         consoleErrors.length ? `Found ${consoleErrors.length} errors` : '');

    if (consoleErrors.length && VERBOSE) {
        consoleErrors.slice(0, 5).forEach(err => {
            console.log(`    ERROR: ${err.substring(0, 100)}`);
        });
    }
}

async function main() {
    console.log('='.repeat(60));
    console.log('PITCHRANK FRONTEND AUDIT');
    console.log(`Base URL: ${BASE_URL}`);
    console.log('='.repeat(60));

    const browser = await chromium.launch({
        headless: true,
        executablePath: '/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome'
    });
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const page = await context.newPage();

    try {
        await auditHomePage(page);
        await auditRankingsPage(page);
        await auditTeamsPage(page);
        await auditLoginPage(page);
        await auditMethodologyPage(page);
        await auditNavigation(page);
        await auditMobileResponsiveness(page);
        await auditConsoleErrors(page);
    } catch (e) {
        console.log(`\nFATAL ERROR: ${e.message}`);
        await page.screenshot({ path: '/tmp/audit_fatal_error.png' });
        failed++;
    } finally {
        await browser.close();
    }

    // Print summary
    console.log('\n' + '='.repeat(60));
    console.log('AUDIT SUMMARY');
    console.log('='.repeat(60));
    console.log(`\nPassed: ${passed}`);
    console.log(`Failed: ${failed}`);
    console.log(`Total:  ${passed + failed}`);

    if (errors.length) {
        console.log('\nErrors:');
        errors.forEach(({ name, error }) => {
            console.log(`  - ${name}: ${error}`);
        });
    }

    console.log('\nScreenshots saved to /tmp/audit_*.png');
    console.log('='.repeat(60));

    process.exit(failed === 0 ? 0 : 1);
}

main().catch(e => {
    console.error('Fatal error:', e);
    process.exit(1);
});
