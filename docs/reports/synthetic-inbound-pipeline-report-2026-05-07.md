# Synthetic Inbound Pipeline Report

- Generated: 2026-05-07 16:34 UTC
- Cases run: 20
- Guest-draft outcomes: 11
- Gate-skipped outcomes: 1
- Gate-review outcomes: 1
- Hard parse failures: 3

| Case | Category | Source Route | LLM | Parse | Parser Source | Guest Turn | Gate | Dispatch | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vrbo_initial_inquiry | vrbo_guest | ota/vrbo/ota | success | parsed | llm_email_extractor_anthropic | Hi, we are checking in on May 16. Is early check in possi... | guest_message:0.95 | pre_booking_new | - |
| vrbo_guest_reply_pool | vrbo_guest | ota/vrbo/ota | success | parsed | llm_email_extractor_anthropic | Thanks so much. Is the pool heated in mid-August? | guest_message:0.95 | pre_booking_new | - |
| vrbo_pricing_push | vrbo_guest | ota/vrbo/ota | success | parsed | llm_email_extractor_anthropic | If the price cannot come down I will pass. If the price c... | guest_message:0.95 | pre_booking_new | - |
| vrbo_html_wrapper_fallback | vrbo_fallback | ota/vrbo/ota | fallback | parsed | generic_gmail_parser | Hi Jan, The laundry is on the main floor. On Tue, Sep 30,... | guest_message:0.95 | pre_booking_new | Forces deterministic OTA fallback |
| vrbo_metadata_only_hard_fail | vrbo_noise | ota/vrbo/ota | parse_failure | hard_parse_failure | none | - | guest_message:0.95 | not_executed | Expected hard parse failure on empty guest turn |
| airbnb_guest_airfryer | airbnb_guest | ota/airbnb/ota | success | parsed | llm_email_extractor_anthropic | I know this might sound silly - but does the home have an... | guest_message:0.95 | pre_booking_new | - |
| airbnb_guest_beach_distance | airbnb_guest | ota/airbnb/ota | success | parsed | llm_email_extractor_anthropic | How far is the beach from this house via bike or golf cart? | guest_message:0.95 | pre_booking_new | - |
| airbnb_booking_initial_notification | airbnb_ops | ota/airbnb/ota | fallback | parsed | generic_gmail_parser | RESPOND TO KERI'S INQUIRY Pre-approve / Decline YOU HAVE ... | operational_notification:0.95 | pre_booking_gate_skipped | Operational Airbnb wrapper should be skipped by gate |
| airbnb_reminder_notification | airbnb_ops | ota/airbnb/ota | fallback | parsed | generic_gmail_parser | RESPOND TO KERI'S INQUIRY Maintain your response rate and... | operational_notification:0.95 | not_executed | Skipped before draft generation |
| airbnb_resolution_center | airbnb_ops | ota/airbnb/ota | fallback | parsed | generic_gmail_parser | A guest has filed a reimbursement request for damages. | operational_notification:0.95 | not_executed | - |
| direct_webform_occupancy | direct_guest | direct_website_form/direct/direct_website_form | success | parsed | llm_email_extractor_anthropic | Are you allowed to purchase extra wrist bands? | guest_message:0.95 | pre_booking_new | - |
| direct_webform_pricing_change | direct_guest | direct_website_form/direct/direct_website_form | success | parsed | llm_email_extractor_anthropic | The total for our dates was $7070. Did something happen t... | guest_message:0.95 | pre_booking_new | - |
| direct_guest_reply_pet_policy | direct_guest | generic_email/direct/generic | success | parsed | llm_email_extractor_anthropic | Are we able to bring a small dog? | guest_message:0.95 | pre_booking_new | - |
| generic_pool_heat_question | generic_guest | generic_email/direct/generic | success | parsed | llm_email_extractor_anthropic | Can the pool be heated? | guest_message:0.95 | pre_booking_new | - |
| generic_ooo | system_noise | generic_email/direct/generic | parse_failure | hard_parse_failure | none | - | bounce_or_system:0.95 | not_executed | - |
| generic_bounce | system_noise | generic_email/direct/generic | parse_failure | hard_parse_failure | none | - | bounce_or_system:0.95 | not_executed | - |
| generic_marketing_newsletter | marketing_noise | generic_email/direct/generic | fallback | skipped | none | - | marketing:0.95 | not_executed | - |
| vendor_beach_setup_ops | vendor_ops | vendor_ops_email/direct/vendor_ops_email | fallback | parsed | vendor_ops_email_parser | Beach chair setup list for Friday arrivals attached. | disabled | not_executed | Vendor coordination route, not a guest draft path |
| airbnb_unclear_low_confidence | gate_review | ota/airbnb/ota | success | parsed | llm_email_extractor_anthropic | Please call me. | guest_message:0.55 | pre_booking_gate_review | Low-confidence guest message should route to review |
| direct_gate_review_all | gate_review | generic_email/direct/generic | success | parsed | llm_email_extractor_anthropic | Just checking whether there is parking for three cars. | guest_message:0.92 | pre_booking_new | Observed behavior: review-all does not override proceed=true guest messages |
