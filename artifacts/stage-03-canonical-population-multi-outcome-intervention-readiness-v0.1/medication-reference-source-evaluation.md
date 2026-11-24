# Medication reference source evaluation

- **ATC**: Anatomical Therapeutic Chemical classification (suitability: Useful hierarchy; not sufficient alone for product-level dosing)
- **RxNorm**: US normalized drug terminology (suitability: Strong for US product concepts; jurisdiction mismatch for local clinic data)
- **National drug registries (jurisdiction-local)**: Local authorized medicinal products (suitability: Preferred for local product identity when licensed for project use)
- **Active-ingredient catalogs**: Ingredient-level identity independent of brand (suitability: Useful bridge from free-text to substance)
- **Dose-form and route dictionaries**: Normalize form/route vocabulary (suitability: Needed for episode construction quality)
- **Interaction / contraindication sources**: Safety interaction knowledge (suitability: Deferred; not integrated in this stage)
- **PK/PD reference sources**: Pharmacokinetic/pharmacodynamic parameters (suitability: Out of scope for this stage (pkpd_status: NOT_STARTED))

No restricted commercial DB downloaded or integrated.
