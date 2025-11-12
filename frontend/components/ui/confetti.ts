import confetti from 'canvas-confetti';

/**
 * Launch confetti celebration
 * Used when a watched team reaches #1 ranking
 */
export function launchConfetti() {
  confetti({
    particleCount: 120,
    spread: 70,
    origin: { y: 0.7 },
    colors: ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ef4444'],
  });
  
  // Additional burst after short delay
  setTimeout(() => {
    confetti({
      particleCount: 50,
      angle: 60,
      spread: 55,
      origin: { x: 0 },
      colors: ['#10b981', '#3b82f6', '#8b5cf6'],
    });
    confetti({
      particleCount: 50,
      angle: 120,
      spread: 55,
      origin: { x: 1 },
      colors: ['#10b981', '#3b82f6', '#8b5cf6'],
    });
  }, 250);
}

