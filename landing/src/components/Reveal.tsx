import type { CSSProperties, ElementType, ReactNode } from 'react'
import { useInView } from '../lib/useInView'

interface RevealProps {
  children: ReactNode
  as?: ElementType
  delay?: number
  className?: string
  style?: CSSProperties
  rootMargin?: string
  /** state attributes the wrapped block needs, such as `data-hints` */
  [data: `data-${string}`]: unknown
}

export function Reveal({
  children,
  as: Tag = 'div',
  delay = 0,
  className = '',
  style,
  rootMargin,
  ...rest
}: RevealProps) {
  const { ref, inView } = useInView<HTMLDivElement>(
    rootMargin ? { threshold: 0, rootMargin } : undefined,
  )
  return (
    <Tag
      ref={ref}
      {...rest}
      className={`reveal ${className}`.trim()}
      data-visible={inView}
      style={{ transitionDelay: `${delay}ms`, ...style }}
    >
      {children}
    </Tag>
  )
}
