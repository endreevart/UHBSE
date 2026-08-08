import { useEffect, useRef, useState } from 'react'

/**
 * A ratio threshold is unreachable for anything taller than the viewport, and
 * the lab is several screens tall, so the trigger is "the element has entered
 * far enough from the bottom" rather than "enough of it is on screen".
 */
export function useInView<T extends HTMLElement>(
  options: IntersectionObserverInit = { threshold: 0, rootMargin: '0px 0px -14% 0px' },
) {
  const ref = useRef<T | null>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true)
      return
    }
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          setInView(true)
          observer.unobserve(entry.target)
        }
      }
    }, options)
    observer.observe(node)
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { ref, inView }
}

/** 0 → 1 progress of an element travelling through the viewport. */
export function useScrollProgress<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    let frame = 0

    const measure = () => {
      frame = 0
      const rect = node.getBoundingClientRect()
      const vh = window.innerHeight || 1
      const raw = (vh * 0.85 - rect.top) / (rect.height + vh * 0.35)
      setProgress(Math.max(0, Math.min(1, raw)))
    }

    const onScroll = () => {
      if (frame) return
      frame = window.requestAnimationFrame(measure)
    }

    measure()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [])

  return { ref, progress }
}
