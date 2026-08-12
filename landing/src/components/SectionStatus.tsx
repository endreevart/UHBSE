import { StatusStack } from './StatusStack'

export function SectionStatus() {
  return (
    <section className="section" id="status" aria-labelledby="status-heading">
      <div className="shell status">
        <StatusStack headingId="status-heading" />
      </div>
    </section>
  )
}
