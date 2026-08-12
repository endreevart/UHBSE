export const status = {
  kicker: 'Hoja de ruta',
  title: 'Dónde está UHBSE hoy — y qué viene después.',
  lead:
    'Qué está completo, en curso y planificado a continuación. UHBSE es una tecnología de investigación — no está destinada al uso clínico ni sustituye el juicio clínico.',
  sections: [
    {
      id: 'done',
      label: 'Lo que ya está hecho',
      items: [
        {
          id: 'architecture',
          title: 'Arquitectura de UHBSE definida',
          body:
            'El modelo central del motor está definido: representar el estado del sujeto a lo largo del tiempo, aplicar intervenciones y calcular trayectorias biológicas posibles con incertidumbre.',
          status: 'Estado: arquitectura completada.',
        },
        {
          id: 'clinical-foundation',
          title: 'Base de datos fuente preparada',
          body:
            'El proyecto ha establecido una base para trabajar con datos médicos longitudinales. Los conjuntos de datos fuente han sido auditados estructuralmente: los casos clínicos principales y las observaciones de sujetos están definidos.',
          status: 'Estado: auditoría completada.',
        },
        {
          id: 'source-alignment',
          title: 'Fuentes de datos independientes alineadas',
          body:
            'Un método para comparar conjuntos de datos heterogéneos sin vinculación prematura de registros y sin pérdida de procedencia.',
          status: 'Estado: completado.',
        },
        {
          id: 'canonical-model',
          title: 'Modelo unificado de datos biológicos diseñado',
          body: 'Un modelo canónico representa ahora:',
          points: [
            'el sujeto y el estado basal',
            'eventos clínicos',
            'observaciones de laboratorio',
            'intervenciones',
            'cambio temporal',
            'el origen de cada medida',
            'escenarios sintéticos',
            'estados predichos',
          ],
          status: 'Estado: diseño completado; capa de almacenamiento base implementada.',
        },
        {
          id: 'evidence-layers',
          title: 'Hechos, cálculo y predicción separados',
          body:
            'Las observaciones clínicas, los parámetros derivados, los escenarios sintéticos y las predicciones del modelo son tipos de datos distintos — de modo que cada resultado pueda rastrearse hasta su origen y nivel de confianza.',
          status: 'Estado: implementado en la arquitectura y los contratos de datos.',
        },
        {
          id: 'scenario-system',
          title: 'Sistema de escenarios diseñado',
          body:
            'La lógica de ramificación está definida: cambio de dosis, intervención añadida, retorno a un punto de control y continuación por otra trayectoria.',
          status: 'Estado: diseño completado; motor de cálculo pendiente.',
        },
        {
          id: 'infrastructure',
          title: 'Infraestructura de investigación aislada desplegada',
          body:
            'El almacenamiento base para datos estandarizados está operativo. El control de acceso, la procedencia de registros, el historial de cambios reproducible y la gestión segura de secretos están en marcha.',
          status:
            'Estado: infraestructura base operativa; los registros clínicos aún no se han cargado en la nueva capa.',
        },
      ],
    },
    {
      id: 'active',
      label: 'Lo que estamos haciendo ahora',
      items: [
        {
          id: 'live-pilot',
          title: 'Preparación del primer piloto en vivo controlado',
          body:
            'Se está finalizando una ruta segura desde la primera fuente clínica hacia el modelo de investigación estandarizado.',
          points: [
            'Objetivo: un conjunto reproducible de estados longitudinales sin modificar los sistemas médicos fuente.',
          ],
        },
        {
          id: 'biological-state',
          title: 'Formalización del estado biológico del sujeto',
          body: 'Definición de qué medidas forman el estado inicial de un sujeto virtual:',
          points: [
            'antropometría',
            'medidas de laboratorio',
            'diagnósticos e historial',
            'prescripciones',
            'nutrición',
            'actividad',
            'contexto temporal',
            'completitud y calidad de los datos fuente',
          ],
        },
        {
          id: 'math-core',
          title: 'Diseño del núcleo matemático',
          body: 'Una metodología híbrida que combina:',
          points: [
            'physiology-informed modelling',
            'biología de sistemas',
            'enfoques QSP y PK/PD',
            'dependencias bioquímicas',
            'modelos estadísticos',
            'aprendizaje automático',
            'estimación de incertidumbre',
          ],
          status:
            'Los LLM son una capa de interfaz y orquestación; la simulación numérica se basa en métodos matemáticos y estadísticos verificables.',
        },
        {
          id: 'validation-system',
          title: 'Construcción del marco de validación',
          body:
            'Un método para comparar trayectorias calculadas con la dinámica posterior observada del sujeto.',
          points: [
            'error de pronóstico',
            'calibración de incertidumbre',
            'robustez entre cohortes',
            'calidad del pronóstico en el tiempo',
            'reproducibilidad de resultados',
            'razones de desviación',
          ],
        },
      ],
    },
    {
      id: 'next',
      label: 'Lo que viene después',
      items: [
        {
          id: 'dataset',
          title: 'Primer conjunto de datos clínico estandarizado',
          body:
            'Carga controlada del primer conjunto longitudinal limitado en el modelo canónico de UHBSE.',
        },
        {
          id: 'state-reconstruction',
          title: 'Reconstrucción del estado basal',
          body:
            'Un perfil biológico temporal del sujeto en un punto de partida definido, ensamblado a partir de observaciones reales.',
        },
        {
          id: 'narrow-module',
          title: 'Primer módulo de simulación acotado',
          body:
            'El primer piloto se centra en un conjunto limitado de medidas e intervenciones — para medir la calidad del modelo antes de expandir al organismo completo.',
        },
        {
          id: 'retrospective',
          title: 'Validación retrospectiva',
          body:
            'El motor recibe datos hasta un punto temporal elegido, pronostica hacia adelante y compara con lo que se observó realmente.',
        },
        {
          id: 'branching',
          title: 'Ramificación de escenarios',
          body: 'Las estrategias alternativas se vuelven comparables:',
          points: [
            'mantener el manejo actual',
            'cambiar la dosis',
            'cambiar la duración',
            'añadir una intervención',
            'cambiar nutrición o actividad',
            'modelar distinta adherencia',
            'volver a un punto de control',
          ],
        },
        {
          id: 'impact-map',
          title: 'Mapa de impacto',
          body: 'Para cada intervención, el sistema mostrará:',
          points: [
            'qué medidas cambiaron',
            'dirección del cambio',
            'tiempo hasta el efecto',
            'dependencias directas e indirectas',
            'diferencias entre ramas',
            'rango de incertidumbre',
            'razones por las que un escenario se detuvo',
          ],
        },
        {
          id: 'coverage',
          title: 'Mayor cobertura biológica',
          body:
            'Tras validar los primeros módulos, el motor se expande a interacciones entre sistemas metabólico, endocrino, cardiovascular y otros sistemas fisiológicos.',
        },
        {
          id: 'research-tools',
          title: 'Herramientas de investigación',
          body: 'UHBSE admitirá:',
          points: [
            'formulación de hipótesis de investigación',
            'simulación de cohortes virtuales',
            'análisis de sensibilidad',
            'descubrimiento de biomarcadores potenciales',
            'evaluación preliminar de protocolos',
            'selección de los escenarios más informativos para seguimiento',
          ],
        },
        {
          id: 'external-validation',
          title: 'Validación externa',
          body:
            'Validación con datos independientes y estudios conjuntos con organizaciones médicas, centros de investigación y I+D biofarmacéutica.',
        },
      ],
    },
  ],
}
