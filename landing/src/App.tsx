import { Header } from './components/Header'
import { Hero } from './components/Hero'
import { SectionProblem } from './components/SectionProblem'
import { SectionWhat } from './components/SectionWhat'
import { EngineLab } from './components/EngineLab'
import { SectionLayers } from './components/SectionLayers'
import { SectionImpact } from './components/SectionImpact'
import { SectionWhyNow } from './components/SectionWhyNow'
import { SectionPrinciples } from './components/SectionPrinciples'
import { SectionStatus } from './components/SectionStatus'
import { SectionPartners } from './components/SectionPartners'
import { SectionManifesto } from './components/SectionManifesto'
import { Footer } from './components/Footer'

export default function App() {
  return (
    <>
      {/* three slow-drifting washes behind the whole page, fixed so scrolling
          reads as movement through a field rather than past a backdrop */}
      <div className="field" aria-hidden="true">
        <span className="field__blob field__blob--a" />
        <span className="field__blob field__blob--b" />
        <span className="field__blob field__blob--c" />
      </div>

      <Header />
      <main>
        <Hero />
        <SectionProblem />
        <SectionWhat />
        <EngineLab />
        <SectionLayers />
        <SectionImpact />
        <SectionWhyNow />
        <SectionPrinciples />
        <SectionStatus />
        <SectionPartners />
        <SectionManifesto />
      </main>
      <Footer />
    </>
  )
}
