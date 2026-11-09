import confetti from 'canvas-confetti';

export function launchConfetti() {
  // The default fire runs in a blob: worker, which the site's CSP refuses.
  const fire = confetti.create(undefined, { useWorker: false, resize: true });

  // Athletic Editorial brand colors: Forest Green #0B5345, Electric Yellow #F4D03F
  fire({
    particleCount: 120,
    spread: 70,
    origin: { y: 0.7 },
    colors: ['#0B5345', '#F4D03F', '#0B5345', '#F4D03F', '#052E27'],
  });

  // Additional burst after short delay
  setTimeout(() => {
    fire({
      particleCount: 50,
      angle: 60,
      spread: 55,
      origin: { x: 0 },
      colors: ['#0B5345', '#F4D03F', '#052E27'],
    });
    fire({
      particleCount: 50,
      angle: 120,
      spread: 55,
      origin: { x: 1 },
      colors: ['#0B5345', '#F4D03F', '#052E27'],
    });
  }, 250);
}
