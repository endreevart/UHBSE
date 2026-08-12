# Unknown semantics

Application-schema relations without enough metadata to propose a clinical entity mapping.
Infrastructure/extension objects are tracked separately in `infrastructure_inventory`.
Tables with explicit non-entity roles appear under `role_classified_relations`.
Automatic heuristics never emit CONFIRMED status.

## Unknown relations (UNCLASSIFIED)

- `public.abac_rules` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.abacrules_roles` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.address` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.affiliates` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.black_list_users` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.calls_log` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.calls_settings` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.chat_notifier` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.cities` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.company` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.consultations_timeline` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.consultations_timeline_settings` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.countries` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.disable_sms_notifications` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.documents` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.email_confirmation` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.failed_jobs` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.feedback_support` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.jobs` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.log_notification` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.log_notify_requests` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.log_sms` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.log_validation_exception` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.message_file` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.message_read` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.message_type` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.messages` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.notifications` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.password_confirmation` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.password_resets` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.permission_role` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.permissions` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.phone_confirmation` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.profilaxys_users` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.promo_notification` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.push_notification_devices` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.push_notification_log` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.register_promo_marks` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.reviews` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.roles` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.rooms` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.service_products` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.speed_analyst_beacons` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.states` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.user_notification_settings` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.user_pregnants` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.users_abacrules` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.users_notification` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.vacancies` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `public.vacancies_feedback` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `quest_digital.analyses_tags` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `quest_digital.items_tags` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `quest_digital.recommendations_category` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `quest_digital.recommendations_list` (table, role=UNCLASSIFIED) — **UNKNOWN**
- `quest_digital.recommendations_user` (table, role=UNCLASSIFIED) — **UNKNOWN**

## Role-classified relations (non-entity)

- `public.consultation_service_changes` (table, role=WORKFLOW) — **WORKFLOW**
- `public.document_types` (table, role=REFERENCE) — **REFERENCE**
- `public.feedback` (table, role=ATTRIBUTE_CONTAINER) — **ATTRIBUTE_CONTAINER**
- `public.payment_balance` (table, role=WORKFLOW) — **WORKFLOW**
- `public.payment_invoices` (table, role=WORKFLOW) — **WORKFLOW**
- `public.payment_promo_code` (table, role=WORKFLOW) — **WORKFLOW**
- `public.payment_sberbank_orders` (table, role=WORKFLOW) — **WORKFLOW**
- `public.payment_transactions` (table, role=WORKFLOW) — **WORKFLOW**
- `public.questionnaire` (table, role=ATTRIBUTE_CONTAINER) — **ATTRIBUTE_CONTAINER**
- `public.role_user` (table, role=LINK) — **LINK**
- `public.schedule_events` (table, role=WORKFLOW) — **WORKFLOW**
- `public.users_address` (table, role=LINK) — **LINK**
- `public.users_company` (table, role=LINK) — **LINK**
- `public.users_persons` (table, role=LINK) — **LINK**
- `public.users_rating` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.analyses_catalog` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.analyses_codes` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.analyses_labs` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.analyses_pool` (table, role=WORKFLOW) — **WORKFLOW**
- `quest_digital.analyses_weight` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.catalog_labs` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.catalog_weights` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.lab_addresses` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.lab_referral` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.lab_referral_codes` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.lab_referral_regions` (table, role=REFERENCE) — **REFERENCE**
- `quest_digital.link_analyses` (table, role=LINK) — **LINK**

## Excluded relations (technical names)

- `public.doctrine_migration_versions` (table, role=TECHNICAL) — **EXCLUDED**
- `public.migration_versions` (table, role=TECHNICAL) — **EXCLUDED**
- `public.migrations` (table, role=TECHNICAL) — **EXCLUDED**
- `public.oauth_global` (table, role=TECHNICAL) — **EXCLUDED**
- `public.sessions` (table, role=TECHNICAL) — **EXCLUDED**

## Infrastructure inventory

- `public.doctrine_migration_versions` (table) — **INFRASTRUCTURE**
- `public.migration_versions` (table) — **INFRASTRUCTURE**
- `public.migrations` (table) — **INFRASTRUCTURE**
- `public.oauth_global` (table) — **INFRASTRUCTURE**
- `public.sessions` (table) — **INFRASTRUCTURE**
- `public.spatial_ref_sys` (table) — **INFRASTRUCTURE**
- `tiger.addr` (table) — **INFRASTRUCTURE**
- `tiger.addrfeat` (table) — **INFRASTRUCTURE**
- `tiger.bg` (table) — **INFRASTRUCTURE**
- `tiger.county` (table) — **INFRASTRUCTURE**
- `tiger.county_lookup` (table) — **INFRASTRUCTURE**
- `tiger.countysub_lookup` (table) — **INFRASTRUCTURE**
- `tiger.cousub` (table) — **INFRASTRUCTURE**
- `tiger.direction_lookup` (table) — **INFRASTRUCTURE**
- `tiger.edges` (table) — **INFRASTRUCTURE**
- `tiger.faces` (table) — **INFRASTRUCTURE**
- `tiger.featnames` (table) — **INFRASTRUCTURE**
- `tiger.geocode_settings` (table) — **INFRASTRUCTURE**
- `tiger.geocode_settings_default` (table) — **INFRASTRUCTURE**
- `tiger.loader_lookuptables` (table) — **INFRASTRUCTURE**
- `tiger.loader_platform` (table) — **INFRASTRUCTURE**
- `tiger.loader_variables` (table) — **INFRASTRUCTURE**
- `tiger.pagc_gaz` (table) — **INFRASTRUCTURE**
- `tiger.pagc_lex` (table) — **INFRASTRUCTURE**
- `tiger.pagc_rules` (table) — **INFRASTRUCTURE**
- `tiger.place` (table) — **INFRASTRUCTURE**
- `tiger.place_lookup` (table) — **INFRASTRUCTURE**
- `tiger.secondary_unit_lookup` (table) — **INFRASTRUCTURE**
- `tiger.state` (table) — **INFRASTRUCTURE**
- `tiger.state_lookup` (table) — **INFRASTRUCTURE**
- `tiger.street_type_lookup` (table) — **INFRASTRUCTURE**
- `tiger.tabblock` (table) — **INFRASTRUCTURE**
- `tiger.tabblock20` (table) — **INFRASTRUCTURE**
- `tiger.tract` (table) — **INFRASTRUCTURE**
- `tiger.zcta5` (table) — **INFRASTRUCTURE**
- `tiger.zip_lookup` (table) — **INFRASTRUCTURE**
- `tiger.zip_lookup_all` (table) — **INFRASTRUCTURE**
- `tiger.zip_lookup_base` (table) — **INFRASTRUCTURE**
- `tiger.zip_state` (table) — **INFRASTRUCTURE**
- `tiger.zip_state_loc` (table) — **INFRASTRUCTURE**
- `topology.layer` (table) — **INFRASTRUCTURE**
- `topology.topology` (table) — **INFRASTRUCTURE**
