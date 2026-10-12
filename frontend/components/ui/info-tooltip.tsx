'use client';

import * as React from 'react';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import { Info } from 'lucide-react';

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

// globals.css repeats this query for the 16px input size that stops iOS zooming; change both.
const TOUCH_MEDIA_QUERY = '(hover: none) and (pointer: coarse)';

// Radix sizes the panel's wrapper to max-content, so an uncapped panel is one line of text
// wide; Radix sets --radix-popper-available-width for both the popover and the tooltip.
const PANEL_MAX_WIDTH = 'max-w-[min(20rem,var(--radix-popper-available-width))]';

function useIsTouchDevice(): boolean {
  const [isTouch, setIsTouch] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia(TOUCH_MEDIA_QUERY);
    const update = () => setIsTouch(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, []);
  return isTouch;
}

export interface InfoTooltipProps {
  /** Button that opens the tooltip — `InfoButton`, or a button wrapping the stat it explains. */
  trigger: React.ReactNode;
  /** Content to render inside the tooltip. */
  children: React.ReactNode;
  /**
   * Extra classes for the content panel. A `max-w-*` here replaces the default cap, so keep
   * the `min(…, var(--radix-popper-available-width))` form to stay inside narrow screens.
   */
  className?: string;
  /** Side of the trigger (Radix `side`). On touch screens `left`/`right` are ignored and the panel opens below. */
  side?: 'top' | 'right' | 'bottom' | 'left';
  /** Offset from the trigger, matches Radix `sideOffset`. */
  sideOffset?: number;
}

/**
 * Hover on pointer devices, tap-to-toggle on touch devices.
 * Use for triggers whose only purpose is to reveal help text — an info icon, or a
 * button wrapping the stat or score it explains. The trigger must not carry a
 * click handler of its own, since on touch the trigger both toggles the popover
 * and fires any attached onClick.
 *
 * For tooltips on controls with an action of their own (sort buttons, toggles), keep
 * the plain Tooltip/TooltipContent/TooltipTrigger — those handle desktop hover
 * safely and degrade predictably on touch.
 */
export function InfoTooltip({ trigger, children, className, side, sideOffset = 0 }: InfoTooltipProps) {
  const isTouch = useIsTouchDevice();
  const panelClasses = cn(
    `bg-foreground text-background z-50 w-fit ${PANEL_MAX_WIDTH} rounded-md px-3 py-1.5 text-xs text-balance`,
    className
  );

  if (isTouch) {
    return (
      <PopoverPrimitive.Root>
        <PopoverPrimitive.Trigger asChild data-slot="info-tooltip-trigger">
          {trigger}
        </PopoverPrimitive.Trigger>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            data-slot="info-tooltip-content"
            // Radix can flip a left/right panel but not slide it along the edge, so on a phone it
            // runs off screen; above/below slides into view.
            side={side === 'left' || side === 'right' ? undefined : side}
            sideOffset={sideOffset}
            className={panelClasses}
          >
            {children}
            <PopoverPrimitive.Arrow className="bg-foreground fill-foreground z-50 size-2.5 translate-y-[calc(-50%_-_2px)] rotate-45 rounded-[2px]" />
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>{trigger}</TooltipTrigger>
      <TooltipContent className={cn(PANEL_MAX_WIDTH, className)} side={side} sideOffset={sideOffset}>
        {children}
      </TooltipContent>
    </Tooltip>
  );
}

/** Info-icon button with a 24px hit area; the usual InfoTooltip trigger. */
export function InfoButton({
  label,
  iconClassName,
  className,
  ...props
}: React.ComponentProps<'button'> & { label: string; iconClassName?: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      className={cn(
        '-m-1 inline-flex size-6 shrink-0 cursor-help items-center justify-center rounded-full text-muted-foreground hover:text-foreground',
        className
      )}
      {...props}
    >
      <Info className={cn('h-3.5 w-3.5', iconClassName)} />
    </button>
  );
}
