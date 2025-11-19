import { cn } from "@/lib/utils";

interface DiagonalSlashProps {
  className?: string;
  size?: "sm" | "md" | "lg" | "xl";
  position?: "left" | "right" | "center";
}

const sizeClasses = {
  sm: "w-1 h-12",
  md: "w-2 h-20",
  lg: "w-2.5 h-32",
  xl: "w-3 h-40",
};

const positionClasses = {
  left: "left-0",
  right: "right-0",
  center: "left-1/2 -translate-x-1/2",
};

/**
 * DiagonalSlash - Athletic Editorial accent element
 *
 * A signature yellow diagonal slash that can be positioned
 * anywhere on the page for visual accent and brand consistency.
 *
 * @example
 * <DiagonalSlash size="lg" position="left" />
 */
export function DiagonalSlash({
  className,
  size = "md",
  position = "left"
}: DiagonalSlashProps) {
  return (
    <div
      className={cn(
        "absolute bg-accent -skew-x-12 pointer-events-none",
        sizeClasses[size],
        positionClasses[position],
        className
      )}
      aria-hidden="true"
    />
  );
}

/**
 * DiagonalSlashContainer - Container for content with diagonal slash accent
 *
 * Wraps content with a positioned diagonal slash accent.
 *
 * @example
 * <DiagonalSlashContainer slashSize="lg" slashPosition="left">
 *   <h1>Your Content</h1>
 * </DiagonalSlashContainer>
 */
export function DiagonalSlashContainer({
  children,
  slashSize = "md",
  slashPosition = "left",
  className,
}: {
  children: React.ReactNode;
  slashSize?: "sm" | "md" | "lg" | "xl";
  slashPosition?: "left" | "right" | "center";
  className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <DiagonalSlash size={slashSize} position={slashPosition} />
      {children}
    </div>
  );
}
