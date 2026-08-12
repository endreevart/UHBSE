export const status = {
  kicker: 'Roadmap',
  title: 'Wo UHBSE heute steht — und was als Nächstes kommt.',
  lead:
    'Was abgeschlossen ist, was in Arbeit ist und was als Nächstes geplant ist. UHBSE ist eine Forschungstechnologie — nicht für den klinischen Einsatz und kein Ersatz für klinisches Urteilsvermögen.',
  sections: [
    {
      id: 'done',
      label: 'Was bereits erledigt ist',
      items: [
        {
          id: 'architecture',
          title: 'UHBSE-Architektur definiert',
          body:
            'Das Kernmodell des Engines ist definiert: Zustand des Subjekts über die Zeit darstellen, Interventionen anwenden und mögliche biologische Trajektorien mit Unsicherheit berechnen.',
          status: 'Status: Architektur abgeschlossen.',
        },
        {
          id: 'clinical-foundation',
          title: 'Grundlage der Quelldaten vorbereitet',
          body:
            'Das Projekt hat eine Grundlage für die Arbeit mit longitudinalen medizinischen Daten geschaffen. Die Quelldatensätze wurden strukturell auditiert: zentrale klinische Fälle und Subjektbeobachtungen sind definiert.',
          status: 'Status: Audit abgeschlossen.',
        },
        {
          id: 'source-alignment',
          title: 'Unabhängige Datenquellen abgeglichen',
          body:
            'Eine Methode zum Vergleich heterogener Datensätze ohne vorzeitige Datensatzverknüpfung und ohne Verlust der Herkunft.',
          status: 'Status: abgeschlossen.',
        },
        {
          id: 'canonical-model',
          title: 'Einheitliches biologisches Datenmodell entworfen',
          body: 'Ein kanonisches Modell stellt dar:',
          points: [
            'das Subjekt und den Ausgangszustand',
            'klinische Ereignisse',
            'Laborbeobachtungen',
            'Interventionen',
            'zeitliche Veränderung',
            'die Quelle jedes Messwerts',
            'synthetische Szenarien',
            'vorhergesagte Zustände',
          ],
          status: 'Status: Design abgeschlossen; Basisspeicherschicht implementiert.',
        },
        {
          id: 'evidence-layers',
          title: 'Fakten, Berechnung und Prognose getrennt',
          body:
            'Klinische Beobachtungen, abgeleitete Parameter, synthetische Szenarien und Modellvorhersagen sind unterschiedliche Datentypen — sodass jedes Ergebnis auf seinen Ursprung und sein Vertrauensniveau zurückgeführt werden kann.',
          status: 'Status: in Architektur und Datenverträgen implementiert.',
        },
        {
          id: 'scenario-system',
          title: 'Szenariosystem entworfen',
          body:
            'Verzweigungslogik ist definiert: Dosisänderung, zusätzliche Intervention, Rückkehr zu einem Kontrollpunkt und Fortsetzung entlang einer anderen Trajektorie.',
          status: 'Status: Design abgeschlossen; Rechen-Engine steht noch aus.',
        },
        {
          id: 'infrastructure',
          title: 'Isolierte Forschungsinfrastruktur bereitgestellt',
          body:
            'Basisspeicher für standardisierte Daten ist betriebsbereit. Zugriffskontrolle, Datensatzherkunft, reproduzierbare Änderungshistorie und sichere Geheimnisverwaltung sind eingerichtet.',
          status:
            'Status: Basisinfrastruktur betriebsbereit; klinische Datensätze sind in der neuen Schicht noch nicht geladen.',
        },
      ],
    },
    {
      id: 'active',
      label: 'Was wir gerade tun',
      items: [
        {
          id: 'live-pilot',
          title: 'Vorbereitung des ersten kontrollierten Live-Piloten',
          body:
            'Ein sicherer Weg von der ersten klinischen Quelle in das standardisierte Forschungsmodell wird finalisiert.',
          points: [
            'Ziel: ein reproduzierbarer Satz longitudinaler Zustände ohne Änderung der Quellmedizinsysteme.',
          ],
        },
        {
          id: 'biological-state',
          title: 'Biologischen Zustand des Subjekts formalisieren',
          body: 'Festlegung, welche Messwerte den Ausgangszustand eines virtuellen Subjekts bilden:',
          points: [
            'Anthropometrie',
            'Laborwerte',
            'Diagnosen und Anamnese',
            'Verordnungen',
            'Ernährung',
            'Aktivität',
            'zeitlicher Kontext',
            'Vollständigkeit und Qualität der Quelldaten',
          ],
        },
        {
          id: 'math-core',
          title: 'Mathematischen Kern entwerfen',
          body: 'Eine hybride Methodik, die vereint:',
          points: [
            'physiology-informed modelling',
            'Systembiologie',
            'QSP- und PK/PD-Ansätze',
            'biochemische Abhängigkeiten',
            'statistische Modelle',
            'maschinelles Lernen',
            'Unsicherheitsschätzung',
          ],
          status:
            'LLMs sind eine Schnittstellen- und Orchestrierungsschicht; die numerische Simulation basiert auf überprüfbaren mathematischen und statistischen Methoden.',
        },
        {
          id: 'validation-system',
          title: 'Validierungsrahmen aufbauen',
          body:
            'Eine Methode zum Vergleich berechneter Trajektorien mit beobachteter nachfolgender Subjektdynamik.',
          points: [
            'Prognosefehler',
            'Kalibrierung der Unsicherheit',
            'Robustheit über Kohorten',
            'Prognosequalität über die Zeit',
            'Reproduzierbarkeit der Ergebnisse',
            'Gründe für Abweichungen',
          ],
        },
      ],
    },
    {
      id: 'next',
      label: 'Was als Nächstes kommt',
      items: [
        {
          id: 'dataset',
          title: 'Erster standardisierter klinischer Datensatz',
          body:
            'Kontrolliertes Laden des ersten begrenzten longitudinalen Satzes in das kanonische UHBSE-Modell.',
        },
        {
          id: 'state-reconstruction',
          title: 'Rekonstruktion des Ausgangszustands',
          body:
            'Ein zeitliches biologisches Profil des Subjekts zu einem definierten Startpunkt, zusammengestellt aus realen Beobachtungen.',
        },
        {
          id: 'narrow-module',
          title: 'Erstes eng gefasstes Simulationsmodul',
          body:
            'Der erste Pilot konzentriert sich auf eine begrenzte Menge von Messwerten und Interventionen — um die Modellqualität vor der Ausweitung auf den Gesamtorganismus zu messen.',
        },
        {
          id: 'retrospective',
          title: 'Retrospektive Validierung',
          body:
            'Die Engine erhält Daten bis zu einem gewählten Zeitpunkt, prognostiziert nach vorne und vergleicht mit dem, was tatsächlich beobachtet wurde.',
        },
        {
          id: 'branching',
          title: 'Szenarioverzweigung',
          body: 'Alternative Strategien werden vergleichbar:',
          points: [
            'aktuelles Management beibehalten',
            'Dosis ändern',
            'Dauer ändern',
            'eine Intervention hinzufügen',
            'Ernährung oder Aktivität ändern',
            'unterschiedliche Adhärenz modellieren',
            'zu einem Kontrollpunkt zurückkehren',
          ],
        },
        {
          id: 'impact-map',
          title: 'Wirkungskarte',
          body: 'Für jede Intervention zeigt das System:',
          points: [
            'welche Messwerte sich geändert haben',
            'Richtung der Veränderung',
            'Zeit bis zum Effekt',
            'direkte und indirekte Abhängigkeiten',
            'Unterschiede zwischen Verzweigungen',
            'Unsicherheitsbereich',
            'Gründe für den Stopp eines Szenarios',
          ],
        },
        {
          id: 'coverage',
          title: 'Breitere biologische Abdeckung',
          body:
            'Nach Validierung der ersten Module erweitert sich die Engine auf Wechselwirkungen zwischen metabolischen, endokrinen, kardiovaskulären und anderen physiologischen Systemen.',
        },
        {
          id: 'research-tools',
          title: 'Forschungswerkzeuge',
          body: 'UHBSE wird unterstützen:',
          points: [
            'Bildung von Forschungshypothesen',
            'Simulation virtueller Kohorten',
            'Sensitivitätsanalyse',
            'Entdeckung potenzieller Biomarker',
            'vorläufige Protokollbewertung',
            'Auswahl der informativsten Szenarien für die Nachverfolgung',
          ],
        },
        {
          id: 'external-validation',
          title: 'Externe Validierung',
          body:
            'Validierung an unabhängigen Daten und gemeinsame Studien mit medizinischen Organisationen, Forschungszentren und Biopharma-F&E.',
        },
      ],
    },
  ],
}
