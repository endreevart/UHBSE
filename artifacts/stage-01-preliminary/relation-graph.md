# Relation graph

Application-schema candidate relations and foreign-key edges (metadata only).

```mermaid
flowchart LR
  N0["magerya_api.account_patient"]
  N1["magerya_api.appointment_appointment"]
  N2["magerya_api.appointment_appointmentrequest"]
  N3["magerya_api.appointment_callbackrequest"]
  N4["magerya_api.diagnosis_diagnosis_appointment_recommendations"]
  N5["magerya_api.document_document"]
  N2 --> N1
  N1 --> N1
  N1 --> N0
  N2 --> N0
  N1 --> N0
  N2 --> N0
  N5 --> N1
  N5 --> N0
```
