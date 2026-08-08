/** Fixed-width week label for transport and header readouts (always one decimal). */
export function formatWeekSlot(week: number): string {
  return (Math.round(week * 2) / 2).toFixed(1)
}
