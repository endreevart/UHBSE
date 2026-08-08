import { useEffect, useRef, useState } from 'react'

/**
 * The rendered width of an element, in CSS pixels.
 *
 * Diagrams laid out in a fixed viewBox either letterbox or scale their type
 * when the pane is a different width than the drawing. Measuring lets the
 * drawing be built at the pane's real width instead, so time stretches across
 * whatever room there is while labels stay the size they were designed at.
 *
 * `fallback` is what server-side and first-paint code sees, before the
 * observer has reported anything.
 */
export function useElementWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(fallback)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    const observer = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width
      // sub-pixel churn from scrollbars and zoom would otherwise rebuild the
      // diagram on every frame of a resize
      setWidth((prev) => (Math.abs(prev - w) < 1 ? prev : w))
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return { ref, width }
}
