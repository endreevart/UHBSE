import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import type { Vec } from '../lib/curve'
import {
  createRenderer,
  createScene,
  fitCamera,
  pickBranchAtWorld,
  screenToSvg,
  syncBranchLines,
  syncSceneDecor,
  type BranchLineSyncOptions,
  type GlNormalizedRibbon,
} from '../lib/ensembleGl'
import {
  FAN_SPREAD_STEP,
  FAN_ZOOM_STEP,
  clampFanSpread,
  clampFanZoom,
  constrainFanView,
  fanCameraRect,
  zoomViewAt,
  type FanView,
  type FanViewContext,
} from '../lib/ensembleViewport'
import type { TreeBranch } from '../lib/trajectoryTree'

const DRAG_THRESHOLD = 5

interface Options {
  branches: TreeBranch[]
  medianPts: Vec[]
  fanView: FanView
  fanCtx: FanViewContext
  selectedBranch: number | null
  onSelectBranch: (index: number | null) => void
  onFanView: (updater: (v: FanView) => FanView) => void
  onPanning?: (panning: boolean) => void
  zoom?: number
  bestBranchIndex?: number | null
  showNormalizedPanel?: boolean
  normalizedMedians?: GlNormalizedRibbon[]
}

export function useEnsembleGl(
  containerRef: React.RefObject<HTMLDivElement | null>,
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  {
    branches,
    medianPts,
    fanView,
    fanCtx,
    selectedBranch,
    onSelectBranch,
    onFanView,
    onPanning,
    zoom = 1,
    bestBranchIndex = null,
    showNormalizedPanel = false,
    normalizedMedians = [],
  }: Options,
) {
  const sceneRef = useRef<ReturnType<typeof createScene> | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const aspectRef = useRef(16 / 9)
  const panningRef = useRef(false)
  const pointerDownRef = useRef({ x: 0, y: 0 })

  const fanViewRef = useRef(fanView)
  fanViewRef.current = fanView
  const fanCtxRef = useRef(fanCtx)
  fanCtxRef.current = fanCtx
  const branchesRef = useRef(branches)
  branchesRef.current = branches
  const medianPtsRef = useRef(medianPts)
  medianPtsRef.current = medianPts
  const selectedRef = useRef(selectedBranch)
  selectedRef.current = selectedBranch
  const onSelectRef = useRef(onSelectBranch)
  onSelectRef.current = onSelectBranch
  const onFanViewRef = useRef(onFanView)
  onFanViewRef.current = onFanView
  const onPanningRef = useRef(onPanning)
  onPanningRef.current = onPanning
  const zoomRef = useRef(zoom)
  zoomRef.current = zoom
  const glOptionsRef = useRef<BranchLineSyncOptions>({})
  glOptionsRef.current = { bestBranchIndex, showNormalizedPanel, normalizedMedians }

  const applyView = (updater: (v: FanView) => FanView) => {
    onFanViewRef.current((v) => constrainFanView(updater(v), fanCtxRef.current))
  }

  const render = () => {
    const renderer = rendererRef.current
    const pack = sceneRef.current
    if (!renderer || !pack) return
    const el = containerRef.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    if (width < 1 || height < 1) return
    aspectRef.current = width / height
    const ctx = { ...fanCtxRef.current, aspect: aspectRef.current }
    renderer.setSize(width, height, false)
    const view = constrainFanView(fanViewRef.current, ctx)
    fitCamera(pack.camera, view, ctx)
    renderer.render(pack.scene, pack.camera)
  }

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const renderer = createRenderer(canvas)
    const pack = createScene()
    rendererRef.current = renderer
    sceneRef.current = pack

    const onResize = () => render()
    const ro = new ResizeObserver(onResize)
    ro.observe(container)

    const setPanning = (on: boolean) => {
      if (panningRef.current === on) return
      panningRef.current = on
      onPanningRef.current?.(on)
      container.dataset.panning = on ? 'true' : 'false'
    }

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = container.getBoundingClientRect()
      const ctx = { ...fanCtxRef.current, aspect: rect.width / rect.height }

      if (e.ctrlKey || e.metaKey) {
        applyView((v) => ({ ...v, spread: clampFanSpread(v.spread * (e.deltaY < 0 ? FAN_SPREAD_STEP : 1 / FAN_SPREAD_STEP)) }))
        render()
        return
      }

      if (Math.abs(e.deltaX) > Math.abs(e.deltaY) * 0.5) {
        const box = fanCameraRect(fanViewRef.current, ctx)
        applyView((v) => ({
          ...v,
          scrollX: v.scrollX + ((e.deltaX + e.deltaY * 0.25) / rect.width) * box.w,
        }))
        render()
        return
      }

      const anchor = screenToSvg(e.clientX, e.clientY, rect, pack.camera)
      const fx = (e.clientX - rect.left) / rect.width
      const fy = (e.clientY - rect.top) / rect.height
      const factor = e.deltaY < 0 ? FAN_ZOOM_STEP : 1 / FAN_ZOOM_STEP
      applyView((v) => {
        const newZoom = clampFanZoom(v.zoom * factor, v.spread, ctx.aspect, ctx.simulationEndWeek)
        return zoomViewAt(v, ctx, anchor.x, anchor.y, fx, fy, newZoom)
      })
      render()
    }

    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0) return
      pointerDownRef.current = { x: e.clientX, y: e.clientY }
      setPanning(false)
      container.setPointerCapture(e.pointerId)
    }

    const onPointerMove = (e: PointerEvent) => {
      if (e.buttons !== 1) return
      const drag = Math.hypot(
        e.clientX - pointerDownRef.current.x,
        e.clientY - pointerDownRef.current.y,
      )
      if (drag < DRAG_THRESHOLD) return

      setPanning(true)
      const rect = container.getBoundingClientRect()
      const ctx = { ...fanCtxRef.current, aspect: rect.width / rect.height }
      const box = fanCameraRect(fanViewRef.current, ctx)
      applyView((v) => ({
        ...v,
        scrollX: v.scrollX - (e.movementX / rect.width) * box.w,
        cy: v.cy - (e.movementY / rect.height) * box.h,
      }))
      render()
    }

    const onPointerUp = (e: PointerEvent) => {
      container.releasePointerCapture(e.pointerId)
      const wasPan = panningRef.current
      setPanning(false)

      const drag = Math.hypot(
        e.clientX - pointerDownRef.current.x,
        e.clientY - pointerDownRef.current.y,
      )
      if (wasPan || drag >= DRAG_THRESHOLD) return

      const rect = container.getBoundingClientRect()
      const ctx = { ...fanCtxRef.current, aspect: rect.width / rect.height }
      const view = constrainFanView(fanViewRef.current, ctx)
      fitCamera(pack.camera, view, ctx)
      const world = screenToSvg(e.clientX, e.clientY, rect, pack.camera)
      const box = fanCameraRect(view, ctx)
      const picked = pickBranchAtWorld(
        branchesRef.current,
        world.x,
        world.y,
        rect.height,
        box.h,
      )
      if (picked !== null) {
        onSelectRef.current(selectedRef.current === picked ? null : picked)
      }
    }

    container.addEventListener('wheel', onWheel, { passive: false })
    container.addEventListener('pointerdown', onPointerDown)
    container.addEventListener('pointermove', onPointerMove)
    container.addEventListener('pointerup', onPointerUp)
    container.addEventListener('pointerleave', onPointerUp)

    const initCtx = { ...fanCtxRef.current, aspect: aspectRef.current }
    syncSceneDecor(pack.branchRoot, fanViewRef.current, initCtx)
    syncBranchLines(
      pack.branchRoot,
      branchesRef.current,
      medianPtsRef.current,
      selectedRef.current,
      zoomRef.current,
      glOptionsRef.current,
    )
    render()

    return () => {
      ro.disconnect()
      container.removeEventListener('wheel', onWheel)
      container.removeEventListener('pointerdown', onPointerDown)
      container.removeEventListener('pointermove', onPointerMove)
      container.removeEventListener('pointerup', onPointerUp)
      container.removeEventListener('pointerleave', onPointerUp)
      renderer.dispose()
      pack.branchRoot.traverse((obj) => {
        if (obj instanceof THREE.Line) {
          obj.geometry.dispose()
          ;(obj.material as THREE.Material).dispose()
        }
      })
    }
  }, [canvasRef, containerRef])

  useEffect(() => {
    const pack = sceneRef.current
    if (!pack) return
    const ctx = { ...fanCtx, aspect: aspectRef.current }
    syncSceneDecor(pack.branchRoot, fanView, ctx)
    syncBranchLines(pack.branchRoot, branches, medianPts, selectedBranch, zoom, {
      bestBranchIndex,
      showNormalizedPanel,
      normalizedMedians,
    })
    render()
  }, [branches, medianPts, fanView, fanCtx, selectedBranch, zoom, bestBranchIndex, showNormalizedPanel, normalizedMedians])
}
