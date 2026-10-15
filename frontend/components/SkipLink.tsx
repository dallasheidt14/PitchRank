'use client';

/**
 * Moves keyboard focus past the header into the page's main content. It focuses `#main` itself rather than
 * following the link: a plain hash link adds a history entry the App Router can't restore on Back.
 */
export function SkipLink() {
  const skip = (event: React.MouseEvent<HTMLAnchorElement>) => {
    const main = document.getElementById('main');
    if (!main) return;
    event.preventDefault();
    // Focusable only for this hand-off, so a click elsewhere on the page doesn't land focus on <main>.
    main.setAttribute('tabindex', '-1');
    main.addEventListener('blur', () => main.removeAttribute('tabindex'), { once: true });
    main.focus();
  };

  return (
    <a
      href="#main"
      onClick={skip}
      className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-primary focus:shadow-md"
    >
      Skip to main content
    </a>
  );
}
