export const status = {
  kicker: 'Feuille de route',
  title: 'Où en est UHBSE aujourd\'hui — et ce qui vient ensuite.',
  lead:
    'Ce qui est terminé, en cours et prévu ensuite. UHBSE est une technologie de recherche — non destinée à un usage clinique et ne remplaçant pas le jugement clinique.',
  sections: [
    {
      id: 'done',
      label: 'Ce qui est déjà fait',
      items: [
        {
          id: 'architecture',
          title: 'Architecture UHBSE définie',
          body:
            'Le modèle central du moteur est défini : représenter l\'état du sujet dans le temps, appliquer des interventions et calculer des trajectoires biologiques possibles avec incertitude.',
          status: 'Statut : architecture terminée.',
        },
        {
          id: 'clinical-foundation',
          title: 'Fondation des données sources préparée',
          body:
            'Le projet a établi une base pour travailler avec des données médicales longitudinales. Les jeux de données sources ont fait l\'objet d\'un audit structurel : les cas cliniques principaux et les observations de sujets sont définis.',
          status: 'Statut : audit terminé.',
        },
        {
          id: 'source-alignment',
          title: 'Sources de données indépendantes alignées',
          body:
            'Une méthode pour comparer des jeux de données hétérogènes sans liaison prématurée des enregistrements et sans perte de provenance.',
          status: 'Statut : terminé.',
        },
        {
          id: 'canonical-model',
          title: 'Modèle unifié de données biologiques conçu',
          body: 'Un modèle canonique représente désormais :',
          points: [
            'le sujet et l\'état de référence',
            'les événements cliniques',
            'les observations de laboratoire',
            'les interventions',
            'l\'évolution temporelle',
            'la source de chaque mesure',
            'les scénarios synthétiques',
            'les états prédits',
          ],
          status: 'Statut : conception terminée ; couche de stockage de base implémentée.',
        },
        {
          id: 'evidence-layers',
          title: 'Faits, calcul et prédiction séparés',
          body:
            'Les observations cliniques, les paramètres dérivés, les scénarios synthétiques et les prédictions du modèle sont des types de données distincts — afin que chaque résultat puisse être rattaché à son origine et à son niveau de confiance.',
          status: 'Statut : implémenté dans l\'architecture et les contrats de données.',
        },
        {
          id: 'scenario-system',
          title: 'Système de scénarios conçu',
          body:
            'La logique de branchement est définie : changement de dose, intervention ajoutée, retour à un point de contrôle et poursuite selon une autre trajectoire.',
          status: 'Statut : conception terminée ; moteur de calcul à venir.',
        },
        {
          id: 'infrastructure',
          title: 'Infrastructure de recherche isolée déployée',
          body:
            'Le stockage de base pour les données standardisées est opérationnel. Le contrôle d\'accès, la provenance des enregistrements, l\'historique des modifications reproductible et la gestion sécurisée des secrets sont en place.',
          status:
            'Statut : infrastructure de base opérationnelle ; les enregistrements cliniques ne sont pas encore chargés dans la nouvelle couche.',
        },
      ],
    },
    {
      id: 'active',
      label: 'Ce que nous faisons maintenant',
      items: [
        {
          id: 'live-pilot',
          title: 'Préparation du premier pilote en direct contrôlé',
          body:
            'Une voie sécurisée depuis la première source clinique vers le modèle de recherche standardisé est en cours de finalisation.',
          points: [
            'Objectif : un ensemble reproductible d\'états longitudinaux sans modification des systèmes médicaux sources.',
          ],
        },
        {
          id: 'biological-state',
          title: 'Formalisation de l\'état biologique du sujet',
          body: 'Définition des mesures qui composent l\'état initial d\'un sujet virtuel :',
          points: [
            'anthropométrie',
            'mesures de laboratoire',
            'diagnostics et antécédents',
            'prescriptions',
            'nutrition',
            'activité',
            'contexte temporel',
            'exhaustivité et qualité des données sources',
          ],
        },
        {
          id: 'math-core',
          title: 'Conception du noyau mathématique',
          body: 'Une méthodologie hybride combinant :',
          points: [
            'physiology-informed modelling',
            'biologie des systèmes',
            'approches QSP et PK/PD',
            'dépendances biochimiques',
            'modèles statistiques',
            'apprentissage automatique',
            'estimation de l\'incertitude',
          ],
          status:
            'Les LLM constituent une couche d\'interface et d\'orchestration ; la simulation numérique repose sur des méthodes mathématiques et statistiques vérifiables.',
        },
        {
          id: 'validation-system',
          title: 'Construction du cadre de validation',
          body:
            'Une méthode pour comparer les trajectoires calculées avec la dynamique ultérieure observée du sujet.',
          points: [
            'erreur de prévision',
            'calibrage de l\'incertitude',
            'robustesse entre cohortes',
            'qualité de prévision dans le temps',
            'reproductibilité des résultats',
            'raisons des écarts',
          ],
        },
      ],
    },
    {
      id: 'next',
      label: 'Ce qui vient ensuite',
      items: [
        {
          id: 'dataset',
          title: 'Premier jeu de données clinique standardisé',
          body:
            'Chargement contrôlé du premier ensemble longitudinal limité dans le modèle canonique UHBSE.',
        },
        {
          id: 'state-reconstruction',
          title: 'Reconstruction de l\'état de référence',
          body:
            'Un profil biologique temporel du sujet à un point de départ défini, assemblé à partir d\'observations réelles.',
        },
        {
          id: 'narrow-module',
          title: 'Premier module de simulation ciblé',
          body:
            'Le premier pilote se concentre sur un ensemble limité de mesures et d\'interventions — pour évaluer la qualité du modèle avant une extension à l\'organisme entier.',
        },
        {
          id: 'retrospective',
          title: 'Validation rétrospective',
          body:
            'Le moteur reçoit les données jusqu\'à un point temporel choisi, prévoit la suite et compare avec ce qui a été réellement observé.',
        },
        {
          id: 'branching',
          title: 'Branchement de scénarios',
          body: 'Les stratégies alternatives deviennent comparables :',
          points: [
            'maintenir la prise en charge actuelle',
            'modifier la dose',
            'modifier la durée',
            'ajouter une intervention',
            'modifier la nutrition ou l\'activité',
            'modéliser une adhérence différente',
            'revenir à un point de contrôle',
          ],
        },
        {
          id: 'impact-map',
          title: 'Carte d\'impact',
          body: 'Pour chaque intervention, le système indiquera :',
          points: [
            'quelles mesures ont changé',
            'direction du changement',
            'délai d\'effet',
            'dépendances directes et indirectes',
            'différences entre branches',
            'plage d\'incertitude',
            'raisons d\'arrêt d\'un scénario',
          ],
        },
        {
          id: 'coverage',
          title: 'Couverture biologique élargie',
          body:
            'Après validation des premiers modules, le moteur s\'étend aux interactions entre les systèmes métabolique, endocrinien, cardiovasculaire et autres systèmes physiologiques.',
        },
        {
          id: 'research-tools',
          title: 'Outils de recherche',
          body: 'UHBSE prendra en charge :',
          points: [
            'la formulation d\'hypothèses de recherche',
            'la simulation de cohortes virtuelles',
            'l\'analyse de sensibilité',
            'la découverte de biomarqueurs potentiels',
            'l\'évaluation préliminaire de protocoles',
            'la sélection des scénarios les plus informatifs pour le suivi',
          ],
        },
        {
          id: 'external-validation',
          title: 'Validation externe',
          body:
            'Validation sur des données indépendantes et études conjointes avec des organisations médicales, des centres de recherche et la R&D biopharmaceutique.',
        },
      ],
    },
  ],
}
