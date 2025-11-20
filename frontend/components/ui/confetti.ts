import confetti from 'canvas-confetti';

/**
 * Launch confetti celebration
 * Used when a watched team reaches #1 ranking
 */
export function launchConfetti() {
  // Athletic Editorial brand colors: Forest Green #0B5345, Electric Yellow #F4D03F
  confetti({
    particleCount: 120,
    spread: 70,
    origin: { y: 0.7 },
    colors: ['#0B5345', '#F4D03F', '#0B5345', '#F4D03F', '#052E27'],
  });

  // Additional burst after short delay
  setTimeout(() => {
    confetti({
      particleCount: 50,
      angle: 60,
      spread: 55,
      origin: { x: 0 },
      colors: ['#0B5345', '#F4D03F', '#052E27'],
    });
    confetti({
      particleCount: 50,
      angle: 120,
      spread: 55,
      origin: { x: 1 },
      colors: ['#0B5345', '#F4D03F', '#052E27'],
    });
  }, 250);
}

