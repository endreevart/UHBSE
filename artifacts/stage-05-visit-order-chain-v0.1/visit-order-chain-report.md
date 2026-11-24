# Visit-to-visit medicine orders v0.1

**Report status: FINAL (aggregate count, not administration)**

Completed clinic and online visits are ordered by `completed_at` for the same patient.
A medicine order is `MedicineAppointments` with status `added`, linked to that visit.
Written visits, second opinions, manipulations, child appointments, and the questionnaire are outside this count.
An added order is the doctor's assignment on the visit. It is not a record that the patient took the medicine.

## Counts

- Clinic and online visits: 47429. Patients: 16846. Consecutive pairs: 30583.
- Visits with an added medicine order: 2676.
- Added links: 18107. Drugs: 3592. Supplements: 14515.
- Pairs with no added order on either visit: 28247.
- Pairs with an order only on the next visit: 1361. Only on the previous visit: 126.
- Same added set: 9. Next visit only adds: 49. Next visit only removes: 11. Both directions: 780.
- Eight pairs share a timestamp. Their order follows the appointment id.
- The recommendation document has a `medicines` section with items on 553 visits (2100 items). That section is not the visit-to-visit order counted above.

## Stage catalog

The stage database does not store the screen titles «Лекарственные препараты» and «Витамины и БАДы».
The medicine catalog has two categories: `drug` (683 entries) and `supplements` (197 entries).
On completed clinic and online visits, status `added` has 3592 `drug` links on 1991 visits and 14515 `supplements` links on 2208 visits.

Of 30583 consecutive pairs, `drug` is empty on both visits in 28704 pairs. The set is the same in 71, only grows in 50, only shrinks in 28, and changes in both directions in 398. It appears only on the next visit in 1126 pairs and only on the previous visit in 206.
`supplements` is empty on both visits in 28520 pairs. The set is the same in 7, only grows in 43, only shrinks in 7, and changes in both directions in 499. It appears only on the next visit in 1323 pairs and only on the previous visit in 184.

The recommendation template category `medicines` is named «Медикаменты». The diagnosis category `activity` is named «Образ жизни».
Status `added` is the stored order status. It is not a record that the patient took the medicine.

## Live stage container

The counts above are from the local restore of the stage dump. The separate stage container on the dev server has 72635 appointments.
30256 of them have a filled recommendation section titled «Медикаменты» or «Препараты и витамины».
6196 have a catalog order with status `added`.
The union is 36449 appointments, 50.2 percent.
The two recommendation titles do not overlap: «Медикаменты» on 16607 appointments, «Препараты и витамины» on 13649.
Catalog orders almost do not overlap those sections.
The owner confirmed this union on 2026-11-17 and stated that a prescription is the fact of the visit: a prescription without a visit cannot exist.
Every row in the union is attached to an appointment. 36333 are on a completed visit, 102 on a canceled visit, and 14 on another status. Catalog orders with status `added` have no rows without an appointment link.
On 2026-11-17 the owner stated: «Это не зафиксированное в бд действие но каждый пациент принимал эти препараты». The scope is this confirmed union. Evidence level is E4. The statement says the intake is not an action recorded in the database. Domain-accepted mappings stay 0. Eligible cells stay 0.

Completed visits in that container: 69152. Patients: 21024. Consecutive pairs: 48128.
Pairs with no prescription on either visit: 13173.
Prescription only on the previous visit: 8384. Only on the next visit: 12824.
The same name set: 90, and in 89 of those the accompanying text differs.
Names only added: 988. Names only removed: 377. Names changed in both directions: 12292.
Eight pairs share a timestamp. The comparison uses name and catalog identifiers inside the database and does not retain the text.

## Named next-visit state

On 2026-11-18 the owner named the state on the next visit: laboratory results and the visit questionnaire, and the questionnaire depends on the visit type.
The owner then included functional studies in that between-visit state, because an ultrasound can be among them.
On the stage container, the doctor questionnaire is the visit completion document. The owner stated on 2026-11-18 that it is present on every visit except manipulations. The doctor enters it, and on a written visit the patient enters it. In both cases the stored result is the doctor questionnaire. The application copies the completed patient questionnaire into the doctor questionnaire when a written visit moves forward.
Completed visits without that document, apart from manipulations: 470 clinic visits and 670 online visits, all on the psychologist scheme, plus 1 written visit and 187 visits with no visit type. Other completed visits of those types have the document. The psychologist scheme also has 279 clinic visits and 217 online visits that do have it.
The functional-studies catalog has 190 entries. 15 of those names contain «узи». The counts below use every received functional-studies result, not the name match.
Among 48128 consecutive completed visits, the next visit has a received functional study in 2145 clinic pairs, 1313 online pairs, 453 written pairs, and 145 second-opinion pairs.
The next visit has both a questionnaire and a received laboratory result or functional study in 6072 clinic pairs, 4565 online pairs, 1654 written pairs, and 543 second-opinion pairs. Manipulation pairs have neither.
Among 48128 consecutive completed visits, the previous visit has the confirmed prescription and the next visit has a doctor questionnaire in 19778 pairs: 7559 clinic, 8495 online, 2404 written, 1308 second-opinion, and 12 with no visit type. Manipulation accounts for 2032 previous prescriptions and no next doctor questionnaire.
Of those 19778 pairs, the next visit also has a received laboratory result or functional study in 7657 pairs: 2857 clinic, 2913 online, 1498 written, 385 second-opinion, and 4 with no visit type.
## Record change between those visits

The comparison covers the 19778 pairs whose previous visit has the confirmed prescription and whose next visit has a doctor questionnaire. Both visits in every one of those pairs have a doctor questionnaire. Answer text and result values stayed inside the database. A changed record is not an effect of the prescription.
Examination text differs between the visits for goal in 12073 pairs, complaints in 8216, anamnesis in 9386, objective status in 8585, and local status in 4809.
Received laboratory sets are empty on both visits in 5649 pairs, present only on the previous visit in 6778, and only on the next visit in 3368. The same set appears in 31 pairs. Where the same analysis is received on both visits, 2554 pairs have that overlap: the stored item values match in 757 and differ in 1797.
Received functional-study sets are empty on both visits in 14299 pairs. The same study appears on both visits in 163 pairs: the stored description matches in 65 and differs in 98.
The gap between the two completed visits is under 7 days in 3312 pairs, 7 to 30 days in 4054, 31 to 90 days in 5852, 91 to 180 days in 3968, and longer than 180 days in 2584. Eight pairs share a timestamp.
Gate 2 stays closed. Readiness stays `NOT_READY`. Eligible cells stay 0.
