import { useSyncExternalStore } from 'react';

const emptySubscribe = () => () => {};

/**
 * False on the server and during hydration, so markup keyed on it hydrates cleanly.
 * True on every other render, including the first render of a mount after client navigation.
 */
export function useIsClient(): boolean {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );
}
