'use client';

import * as React from 'react';
import * as PopoverPrimitive from '@radix-ui/react-popover';

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

/**
 * Hover on pointer devices, tap-to-toggle on touch devices.
 * Use for info icons whose only purpose is to reveal help text — the trigger
 * must not carry a click handler of its own, since on touch the trigger both
 * toggles the popover and fires any attached onClick.
 *
 * For tooltips that wrap actionable elements (buttons, toggles), keep the
 * plain Tooltip/TooltipContent/TooltipTrigger — those handle desktop hover
 * safely and degrade predictably on touch.
 */

const TOUCH_MEDIA_QUERY = '(hover: none) and (pointer: coarse)';

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
  /** Element that opens the tooltip — typically an info icon button. */
  trigger: React.ReactNode;
  /** Content to render inside the tooltip. */
  children: React.ReactNode;
  /** Extra classes for the content panel. */
  className?: string;
  /** Offset from the trigger, matches Radix `sideOffset`. */
  sideOffset?: number;
}

export function InfoTooltip({ trigger, children, className, sideOffset = 0 }: InfoTooltipProps) {
  const isTouch = useIsTouchDevice();
  const panelClasses = cn(
    'bg-foreground text-background z-50 w-fit rounded-md px-3 py-1.5 text-xs text-balance',
    className
  );

  if (isTouch) {
    return (
      <PopoverPrimitive.Root>
        <PopoverPrimitive.Trigger asChild data-slot="info-tooltip-trigger">
          {trigger}
        </PopoverPrimitive.Trigger>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content data-slot="info-tooltip-content" sideOffset={sideOffset} className={panelClasses}>
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
      <TooltipContent className={className} sideOffset={sideOffset}>
        {children}
      </TooltipContent>
    </Tooltip>
  );
}
