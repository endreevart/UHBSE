# Relation graph

Application-schema candidate relations and foreign-key edges (metadata only).

```mermaid
flowchart LR
  N0["public.consultations"]
  N1["public.persons"]
  N2["public.profilaxys_analyses"]
  N3["public.profilaxys_profile"]
  N4["public.users"]
  N5["public.users_profile"]
  N6["quest_digital.analyses_constructor"]
  N7["quest_digital.lab_result"]
  N2 --> N3
  N4 --> N4
  N5 --> N4
  N6 --> N0
  N6 --> N4
```
