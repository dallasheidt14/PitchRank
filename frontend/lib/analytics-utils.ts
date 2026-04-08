export function getDateRange(range: string): { startDate: string; endDate: string } {
  const end = new Date();
  end.setDate(end.getDate() - 1);
  const start = new Date(end);

  switch (range) {
    case '7d':
      start.setDate(start.getDate() - 7);
      break;
    case '90d':
      start.setDate(start.getDate() - 90);
      break;
    default:
      start.setDate(start.getDate() - 28);
  }

  return {
    startDate: start.toISOString().split('T')[0],
    endDate: end.toISOString().split('T')[0],
  };
}

export function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

export function formatPosition(pos: number): string {
  return pos.toFixed(1);
}
