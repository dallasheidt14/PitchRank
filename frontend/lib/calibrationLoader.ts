const CALIBRATION_DIR = ['data', 'calibration'];

function getPublicCalibrationPath(fileName: string) {
  return `/${[...CALIBRATION_DIR, fileName].join('/')}`;
}

async function loadFromFetch<T>(fileName: string): Promise<T | null> {
  if (typeof fetch !== 'function' || typeof window === 'undefined') {
    return null;
  }

  try {
    const response = await fetch(getPublicCalibrationPath(fileName));
    if (!response.ok) {
      return null;
    }

    return (await response.json()) as T;
  } catch {
    return null;
  }
}

async function loadFromFileSystem<T>(fileName: string): Promise<T | null> {
  if (typeof process === 'undefined' || !process.versions?.node) {
    return null;
  }

  try {
    const [{ readFile }, path] = await Promise.all([import('node:fs/promises'), import('node:path')]);
    const candidates = [
      path.join(process.cwd(), 'public', ...CALIBRATION_DIR, fileName),
      path.join(process.cwd(), 'frontend', 'public', ...CALIBRATION_DIR, fileName),
    ];

    for (const candidate of candidates) {
      try {
        const raw = await readFile(candidate, 'utf8');
        return JSON.parse(raw) as T;
      } catch {
        // Try the next candidate path.
      }
    }
  } catch {
    return null;
  }

  return null;
}

export async function loadCalibrationJson<T>(fileName: string): Promise<T | null> {
  if (typeof process !== 'undefined' && process.versions?.node) {
    const fromFileSystem = await loadFromFileSystem<T>(fileName);
    if (fromFileSystem) {
      return fromFileSystem;
    }
  }

  return loadFromFetch<T>(fileName);
}
