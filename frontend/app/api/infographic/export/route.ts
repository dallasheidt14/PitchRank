import { NextRequest, NextResponse } from 'next/server';
import puppeteer from 'puppeteer';

/**
 * GET /api/infographic/export?type=powerscore|movers|ranking|state&variant=square|portrait
 * 
 * Generates a PNG screenshot of the specified infographic.
 * Returns the image directly for download.
 */
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const type = searchParams.get('type') || 'powerscore';
  const variant = searchParams.get('variant') || 'square';
  
  // Map types to render URLs
  const typeToUrl: Record<string, string> = {
    powerscore: '/infographics/powerscore/render',
    movers: '/infographics/movers/render',
    ranking: '/infographics/ranking/render',
    state: '/infographics/state/render',
  };
  
  // Pass through additional query params
  const allParams = new URLSearchParams(searchParams);
  
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
  const targetUrl = `${baseUrl}${typeToUrl[type] || typeToUrl.powerscore}?${allParams.toString()}`;
  
  // Dimensions based on variant
  const dimensions: Record<string, { width: number; height: number }> = {
    square: { width: 1080, height: 1080 },
    portrait: { width: 1080, height: 1350 },
    story: { width: 1080, height: 1920 },
    twitter: { width: 1200, height: 675 },
  };
  
  const { width, height } = dimensions[variant] || dimensions.square;
  
  try {
    const browser = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
    
    const page = await browser.newPage();
    await page.setViewport({ width, height, deviceScaleFactor: 2 });
    
    await page.goto(targetUrl, { 
      waitUntil: 'networkidle0',
      timeout: 30000,
    });
    
    // Wait for the infographic element to render
    const element = await page.waitForSelector('[data-infographic]', { timeout: 5000 }).catch(() => null);
    
    let screenshot;
    if (element) {
      // Screenshot just the infographic element
      screenshot = await element.screenshot({ type: 'png' });
    } else {
      // Fallback to full page clip
      screenshot = await page.screenshot({
        type: 'png',
        clip: { x: 0, y: 0, width, height },
      });
    }
    
    await browser.close();
    
    // Return the image
    return new NextResponse(screenshot, {
      status: 200,
      headers: {
        'Content-Type': 'image/png',
        'Content-Disposition': `attachment; filename="pitchrank-${type}-${variant}.png"`,
        'Cache-Control': 'public, max-age=3600',
      },
    });
  } catch (error) {
    console.error('Error generating infographic:', error);
    return NextResponse.json(
      { error: 'Failed to generate infographic', details: String(error) },
      { status: 500 }
    );
  }
}
