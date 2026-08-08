import * as THREE from 'three'
import type { Vec } from './curve'
import { splitPathAtWeek } from './curve'
import { HORIZON_WEEKS } from '../engine/model'
import {
  tickStepForSpan,
  viewportSpanWeeks,
  weekAtTreeX,
} from './timeRuler'
import {
  LEFT_ANCHOR,
  TIMELINE_END_X,
  fanCameraRect,
  type FanView,
  type FanViewContext,
} from './ensembleViewport'
import type { TreeBranch } from './trajectoryTree'
import type { PipelineBranch } from './pipelineTree'
import {
  TREE_AXIS_Y,
  TREE_BASE_Y,
  TREE_BRANCH_X,
  TREE_END_X,
  TREE_PLOT_TOP,
  TREE_TRUNK_X0,
  treeWeekX,
} from './trajectoryTree'

const OUTCOME_COLOR: Record<TreeBranch['outcome'], number> = {
  improved: 0x7fa3de,
  flat: 0xa8c3ee,
  worsened: 0xc9926f,
  stopped: 0x6e6e6a,
}

const OUTCOME_OPACITY: Record<TreeBranch['outcome'], number> = {
  improved: 0.92,
  flat: 0.38,
  worsened: 0.42,
  stopped: 0.28,
}

const MEDIAN_COLOR = 0xc9926f
const BEST_BRANCH_COLOR = 0x4a9e6f
const GRID_COLOR = 0x2e2e2c

export interface GlNormalizedRibbon {
  pts: Vec[]
  color: number
}

export interface BranchLine {
  index: number
  line: THREE.Line
  hit: THREE.Line
}

/** SVG coordinates: x right, y down → Three.js y up. */
export function svgY(y: number) {
  return -y
}

export function pointsToGeometry(pts: Vec[]): THREE.BufferGeometry {
  const positions = new Float32Array(pts.length * 3)
  for (let i = 0; i < pts.length; i += 1) {
    positions[i * 3] = pts[i].x
    positions[i * 3 + 1] = svgY(pts[i].y)
    positions[i * 3 + 2] = 0
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  return geometry
}

export function fitCamera(camera: THREE.OrthographicCamera, view: FanView, ctx: FanViewContext) {
  const box = fanCameraRect(view, ctx)
  camera.left = box.x
  camera.right = box.x + box.w
  camera.top = -box.y
  camera.bottom = -(box.y + box.h)
  camera.near = -10
  camera.far = 10
  camera.position.set(0, 0, 5)
  camera.updateProjectionMatrix()
}

export function screenToSvg(
  clientX: number,
  clientY: number,
  rect: DOMRect,
  camera: THREE.OrthographicCamera,
): { x: number; y: number } {
  const nx = ((clientX - rect.left) / rect.width) * 2 - 1
  const ny = -((clientY - rect.top) / rect.height) * 2 + 1
  const v = new THREE.Vector3(nx, ny, 0).unproject(camera)
  return { x: v.x, y: -v.y }
}

function offsetPolylineY(pts: Vec[], offset: number): Vec[] {
  if (offset === 0) return pts
  return pts.map((p) => ({ x: p.x, y: p.y + offset }))
}

function haloOffsets(zoom: number): number[] {
  const halo = Math.max(0.15, 2.2 / Math.max(1, zoom))
  return [-halo, 0, halo]
}

function addBranchLine(
  group: THREE.Group,
  pts: Vec[],
  color: number,
  opacity: number,
  order: number,
  zoom: number,
  glow = true,
) {
  if (glow) {
    for (const offset of haloOffsets(zoom)) {
      if (offset === 0) continue
      const halo = new THREE.Line(
        pointsToGeometry(offsetPolylineY(pts, offset)),
        new THREE.LineBasicMaterial({
          color,
          transparent: true,
          opacity: opacity * 0.22,
          depthWrite: false,
        }),
      )
      halo.renderOrder = order - 1
      group.add(halo)
    }
    const coreGlow = new THREE.Line(
      pointsToGeometry(pts),
      new THREE.LineBasicMaterial({
        color,
        transparent: true,
        opacity: opacity * 0.45,
        depthWrite: false,
      }),
    )
    coreGlow.renderOrder = order
    group.add(coreGlow)
  }

  const lineMat = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
  })
  const line = new THREE.Line(pointsToGeometry(pts), lineMat)
  line.renderOrder = order + 1
  group.add(line)
  return line
}

function lineFromCoords(coords: number[], color: number, opacity: number, order: number) {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(coords, 3))
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
  })
  const line = new THREE.Line(geometry, material)
  line.renderOrder = order
  return line
}

export function syncSceneDecor(root: THREE.Group, view?: FanView, ctx?: FanViewContext) {
  const decor = root.children.find((c) => c.name === 'decor')
  if (decor) {
    root.remove(decor)
    decor.traverse((obj) => {
      if (obj instanceof THREE.Line) {
        obj.geometry.dispose()
        ;(obj.material as THREE.Material).dispose()
      }
    })
  }

  const group = new THREE.Group()
  group.name = 'decor'

  const rect = view && ctx ? fanCameraRect(view, ctx) : null
  const x0 = rect ? rect.x - 40 : LEFT_ANCHOR - 20
  const x1 = rect ? rect.x + rect.w + 80 : TIMELINE_END_X + 40
  const y0 = rect ? rect.y - 20 : TREE_PLOT_TOP
  const y1 = rect ? rect.y + rect.h + 20 : TREE_AXIS_Y + 20

  for (let y = Math.floor(y0 / 42) * 42; y <= y1; y += 42) {
    if (y < TREE_PLOT_TOP - 20 || y > TREE_AXIS_Y + 30) continue
    group.add(
      lineFromCoords([x0, svgY(y), 0, x1, svgY(y), 0], GRID_COLOR, 0.35, 0),
    )
  }

  const week0 = weekAtTreeX(x0)
  const week1 = weekAtTreeX(x1)
  const spanWeeks = Math.max(week1 - week0, viewportSpanWeeks(x1 - x0))
  const step = tickStepForSpan(spanWeeks)
  const weekStart = Math.floor(week0 / step) * step
  const weekEnd = week1 + step
  for (let week = weekStart; week <= weekEnd; week += step) {
    if (week < 0 || week > HORIZON_WEEKS + step) continue
    const x = treeWeekX(week)
    if (x < x0 - 20 || x > x1 + 20) continue
    const major = step >= 1 ? Math.abs(week % step) < 0.01 : Math.abs(week % (step * 4)) < step * 0.05
    const beyond = week > HORIZON_WEEKS
    group.add(
      lineFromCoords(
        [x, svgY(TREE_PLOT_TOP), 0, x, svgY(TREE_AXIS_Y - 8), 0],
        GRID_COLOR,
        beyond ? 0.12 : major ? 0.38 : 0.22,
        0,
      ),
    )
  }

  group.add(
    lineFromCoords(
      [TREE_TRUNK_X0, svgY(TREE_BASE_Y), 0, TREE_BRANCH_X, svgY(TREE_BASE_Y), 0],
      0x628ad1,
      0.95,
      1,
    ),
  )

  group.add(
    lineFromCoords(
      [TREE_TRUNK_X0 - 20, svgY(TREE_AXIS_Y), 0, TREE_END_X + 10, svgY(TREE_AXIS_Y), 0],
      GRID_COLOR,
      0.5,
      1,
    ),
  )

  root.add(group)
}

export interface BranchLineSyncOptions {
  bestBranchIndex?: number | null
  showNormalizedPanel?: boolean
  normalizedMedians?: GlNormalizedRibbon[]
}

const STOP_TAIL_COLOR = 0x6e6e6a
const STOP_TAIL_OPACITY = 0.22

function drawBranchSegment(
  group: THREE.Group,
  pts: Vec[],
  color: number,
  opacity: number,
  order: number,
  zoom: number,
  glow: boolean,
): THREE.Line | null {
  if (pts.length < 2) return null
  return addBranchLine(group, pts, color, opacity, order, zoom, glow)
}

export function syncBranchLines(
  root: THREE.Group,
  branches: Array<TreeBranch & { opacity?: number }>,
  medianPts: Vec[],
  selected: number | null,
  zoom = 1,
  options: BranchLineSyncOptions = {},
): BranchLine[] {
  const { bestBranchIndex = null, showNormalizedPanel = false, normalizedMedians = [] } = options
  const branchRoot = root.children.find((c) => c.name === 'branches') as THREE.Group | undefined
  if (branchRoot) {
    root.remove(branchRoot)
    branchRoot.traverse((obj) => {
      if (obj instanceof THREE.Line) {
        obj.geometry.dispose()
        ;(obj.material as THREE.Material).dispose()
      }
    })
  }

  const lines = new THREE.Group()
  lines.name = 'branches'
  const out: BranchLine[] = []
  let bestBranch: (TreeBranch & { opacity?: number }) | null = null

  for (const br of branches) {
    const isBest = !showNormalizedPanel && bestBranchIndex !== null && br.index === bestBranchIndex
    if (isBest) {
      bestBranch = br
      continue
    }

    const pathOutcome = br.pathOutcome ?? br.outcome
    const color = OUTCOME_COLOR[pathOutcome]
    const baseOpacity = OUTCOME_OPACITY[pathOutcome]
    const panelDim = showNormalizedPanel ? 0.1 : 1
    const lineOpacity = (br.opacity ?? 1) * (selected === br.index ? 1 : baseOpacity) * panelDim
    const selectedOn = selected === br.index
    const drawColor = selectedOn ? 0xffffff : color

    const stop = br.stop
    const showStopSplit = stop >= 0 && br.outcome === 'stopped' && !showNormalizedPanel
    const [livePts, tailPts] = showStopSplit
      ? splitPathAtWeek(br.midPts, stop, treeWeekX)
      : [br.midPts, [] as Vec[]]

    const line =
      drawBranchSegment(
        lines,
        livePts,
        drawColor,
        selectedOn ? 1 : lineOpacity,
        selectedOn ? 4 : 2,
        zoom,
        !showNormalizedPanel,
      ) ??
      drawBranchSegment(lines, br.midPts, drawColor, selectedOn ? 1 : lineOpacity, selectedOn ? 4 : 2, zoom, !showNormalizedPanel)
    if (tailPts.length > 1) {
      drawBranchSegment(
        lines,
        tailPts,
        STOP_TAIL_COLOR,
        STOP_TAIL_OPACITY * (br.opacity ?? 1),
        1,
        zoom,
        false,
      )
    }

    const terminal = livePts[livePts.length - 1] ?? br.midPts[br.midPts.length - 1]
    if (terminal && zoom < 250) {
      const dotScale = Math.max(0.35, Math.min(1, 40 / zoom))
      const dotGeo = new THREE.BufferGeometry()
      dotGeo.setAttribute('position', new THREE.Float32BufferAttribute([terminal.x, svgY(terminal.y), 0], 3))
      const dotMat = new THREE.PointsMaterial({
        color: showStopSplit ? STOP_TAIL_COLOR : drawColor,
        size: (showStopSplit ? 4.8 : selectedOn ? 5 : 3.2) * dotScale,
        transparent: true,
        opacity: selectedOn ? 1 : lineOpacity * 0.95,
        sizeAttenuation: false,
      })
      const dot = new THREE.Points(dotGeo, dotMat)
      dot.renderOrder = selectedOn ? 5 : 3
      lines.add(dot)
    }

    const hitMat = new THREE.LineBasicMaterial({
      color,
      transparent: true,
      opacity: 0.001,
      depthWrite: false,
    })
    const hit = new THREE.Line(pointsToGeometry(br.midPts), hitMat)
    hit.userData.branchIndex = br.index
    hit.userData.pickId = (br as PipelineBranch).pickId ?? br.index
    hit.renderOrder = 6
    lines.add(hit)
    if (line) out.push({ index: br.index, line, hit })
  }

  if (showNormalizedPanel) {
    for (const rib of normalizedMedians) {
      addBranchLine(lines, rib.pts, rib.color, 0.84, 2, zoom, true)
    }
  } else {
    addBranchLine(lines, medianPts, MEDIAN_COLOR, 0.95, 3, zoom, true)
    if (bestBranch) {
      const selectedOn = selected === bestBranch.index
      addBranchLine(
        lines,
        bestBranch.midPts,
        BEST_BRANCH_COLOR,
        selectedOn ? 1 : 0.96,
        6,
        zoom,
        true,
      )
      const last = bestBranch.midPts[bestBranch.midPts.length - 1]
      if (last && zoom < 250) {
        const dotScale = Math.max(0.35, Math.min(1, 40 / zoom))
        const dotGeo = new THREE.BufferGeometry()
        dotGeo.setAttribute(
          'position',
          new THREE.Float32BufferAttribute([last.x, svgY(last.y), 0], 3),
        )
        const dotMat = new THREE.PointsMaterial({
          color: BEST_BRANCH_COLOR,
          size: 5.5 * dotScale,
          transparent: true,
          opacity: 0.98,
          sizeAttenuation: false,
        })
        const dot = new THREE.Points(dotGeo, dotMat)
        dot.renderOrder = 7
        lines.add(dot)
      }
    }
  }

  root.add(lines)
  return out
}

export function pickBranch(hits: THREE.Intersection[]): number | null {
  for (const hit of hits) {
    const idx = hit.object.userData.pickId ?? hit.object.userData.branchIndex
    if (typeof idx === 'number') return idx
  }
  return null
}

function distToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax
  const dy = by - ay
  const len2 = dx * dx + dy * dy
  if (len2 === 0) return Math.hypot(px - ax, py - ay)
  let t = ((px - ax) * dx + (py - ay) * dy) / len2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

function distToPolyline(pts: Vec[], x: number, y: number) {
  let min = Infinity
  for (let i = 0; i < pts.length - 1; i += 1) {
    min = Math.min(min, distToSegment(x, y, pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y))
  }
  return min
}

/** Reliable 2D pick — replaces flaky THREE.Line raycasting. */
export function pickBranchAtWorld(
  branches: TreeBranch[],
  worldX: number,
  worldY: number,
  viewportH: number,
  cameraH: number,
): number | null {
  if (worldX < TREE_BRANCH_X - 12) return null

  const pxThreshold = 14
  const threshold = (pxThreshold / Math.max(1, viewportH)) * cameraH

  let best = -1
  let bestDist = Infinity

  for (const br of branches) {
    const pickId = (br as PipelineBranch).pickId ?? br.index
    const dist = distToPolyline(br.midPts, worldX, worldY)
    if (dist < bestDist) {
      bestDist = dist
      best = pickId
    }
  }

  return best >= 0 && bestDist <= threshold ? best : null
}

export function lineHitThreshold(zoom: number) {
  return Math.max(0.08, 2.8 / zoom)
}

export function createRenderer(canvas: HTMLCanvasElement) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setClearColor(0x000000, 0)
  return renderer
}

export function createScene() {
  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera(0, 1, 1, 0, -10, 10)
  const branchRoot = new THREE.Group()
  branchRoot.name = 'root'
  scene.add(branchRoot)
  return { scene, camera, branchRoot }
}
