import type { CSSProperties, ReactNode } from 'react'
import { Reveal } from './Reveal'

type SectionHeadProps = {
  headingId: string
  title: string
  lead?: string
  titleClass?: string
  delay?: number
  titleStyle?: CSSProperties
  footer?: ReactNode
}

export function SectionHead({
  headingId,
  title,
  lead,
  titleClass = 'display display--l',
  delay,
  titleStyle,
  footer,
}: SectionHeadProps) {
  return (
    <Reveal className="section__head" delay={delay}>
      <header>
        <h2 id={headingId} className={titleClass} style={titleStyle}>
          {title}
        </h2>
        {lead ? <p className="lede">{lead}</p> : null}
        {footer}
      </header>
    </Reveal>
  )
}
