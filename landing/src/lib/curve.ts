export interface Vec {
  x: number
  y: number
}

function cubicAt(p0: number, p1: number, p2: number, p3: number, t: number): number {
  const u = 1 - t
  return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3
}

/** Samples an S-shaped branch from (x0,y0) to (x1,y1). */
export function sampleBranch(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  steps = 48,
): Vec[] {
  const c1x = x0 + (x1 - x0) * 0.32
  const c2x = x0 + (x1 - x0) * 0.6
  const out: Vec[] = []
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps
    out.push({
      x: cubicAt(x0, c1x, c2x, x1, t),
      y: cubicAt(y0, y0, y1, y1, t),
    })
  }
  return out
}

export function toPath(points: Vec[]): string {
  if (points.length === 0) return ''
  return points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ')
}

/** Closed ribbon between an upper and a lower sampling of the same curve. */
export function toBand(upper: Vec[], lower: Vec[]): string {
  if (upper.length === 0) return ''
  const forward = upper
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(' ')
  const back = [...lower]
    .reverse()
    .map((p) => `L${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(' ')
  return `${forward} ${back} Z`
}

/** Smooth Catmull-Rom-ish path through arbitrary points. */
export function smoothPath(points: Vec[]): string {
  if (points.length < 2) return toPath(points)
  let d = `M${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i === 0 ? 0 : i - 1]
    const p1 = points[i]
    const p2 = points[i + 1]
    const p3 = points[i + 2] ?? p2
    const c1x = p1.x + (p2.x - p0.x) / 6
    const c1y = p1.y + (p2.y - p0.y) / 6
    const c2x = p2.x - (p3.x - p1.x) / 6
    const c2y = p2.y - (p3.y - p1.y) / 6
    d += ` C${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`
  }
  return d
}

/** Keep only the portion of a branch polyline up to the playhead week. */
export function clipPathAtWeek(pts: Vec[], week: number, weekX: (w: number) => number): Vec[] {
  if (pts.length === 0) return pts
  const xCut = weekX(week)
  if (xCut <= pts[0].x) return [pts[0]]
  if (xCut >= pts[pts.length - 1].x) return pts

  const out: Vec[] = [pts[0]]
  for (let i = 0; i < pts.length - 1; i += 1) {
    const a = pts[i]
    const b = pts[i + 1]
    if (xCut <= a.x) break
    if (xCut < b.x) {
      const t = (xCut - a.x) / (b.x - a.x)
      out.push({ x: xCut, y: a.y + (b.y - a.y) * t })
      break
    }
    out.push(b)
  }
  return out.length > 0 ? out : [pts[0]]
}

/** Split a branch polyline at a week marker — lived path vs terminal tail. */
export function splitPathAtWeek(
  pts: Vec[],
  week: number,
  weekX: (w: number) => number,
): [Vec[], Vec[]] {
  if (pts.length === 0) return [[], []]
  const xCut = weekX(week)
  if (xCut <= pts[0].x) return [[pts[0]], pts]
  if (xCut >= pts[pts.length - 1].x) return [pts, []]

  const before: Vec[] = [pts[0]]
  let split: Vec | null = null
  for (let i = 0; i < pts.length - 1; i += 1) {
    const a = pts[i]
    const b = pts[i + 1]
    if (xCut <= a.x) break
    if (xCut < b.x) {
      const t = (xCut - a.x) / (b.x - a.x)
      split = { x: xCut, y: a.y + (b.y - a.y) * t }
      before.push(split)
      break
    }
    before.push(b)
  }
  if (!split) return [pts, []]

  const after: Vec[] = [split]
  for (let i = 0; i < pts.length - 1; i += 1) {
    if (pts[i + 1].x > xCut + 0.001) after.push(pts[i + 1])
  }
  return [before, after.length > 1 ? after : []]
}
