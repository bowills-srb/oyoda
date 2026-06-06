# Reservation-Aware Routing — Phase 4.3-N

Date: 2026-05-18
Status: Implemented locally as an intake-time routing correction
Scope: inbound email lifecycle determination before pre-booking classification

## Problem

Inbound email routing previously treated `concierge_guest_sessions` as the
only source of truth for deciding whether a guest was already booked. That
missed a real production class of messages:

- the guest has a confirmed PMS reservation
- no concierge session has been provisioned yet
- the email lands in the pre-booking pipeline anyway

Christina Moser was the motivating case. She had a paid Escapia reservation,
but because there was no `concierge_guest_sessions` row yet, the intake path
fell through to pre-booking.

## Phase 4.3-N Choice

This phase intentionally uses the lower-risk path:

- new route kind: `confirmed_guest`
- no automatic concierge-session provisioning
- no pre-booking draft generation for matched confirmed guests

That keeps the change focused on lifecycle correction and observability without
introducing session-creation side effects that have not been audited yet.

## Routing Flow

1. Check `concierge_guest_sessions` as before.
2. If a live session exists, route as `in_stay`.
3. If no session exists, evaluate reservation-aware routing.
4. If a PMS reservation matches conservatively, route as `confirmed_guest`.
5. If there is no match, keep the existing pre-booking path.

## Matching Rules

The match policy is intentionally conservative:

- strongest: `reservation_id`
- next: exact `guest_email`
- fallback only when email is absent: `guest_name + property_code + check_in + check_out`

False positives are treated as worse than false negatives.

## Data Sources

The lookup path reuses existing infrastructure and does not introduce a
parallel Escapia client:

- local `pms_bookings` when data is present
- live Escapia reservation lookup as fallback when credentials are available

Production diagnostic at implementation time showed Beach Habitats currently
has no populated local reservation cache rows in `pms_bookings`, so the live
connector fallback is important for real coverage.

## Safety Controls

- feature flag: `reservation_aware_routing_enabled`
- Beach Habitats default: enabled
- operator settings:
  - `operator_settings.extra.reservation_aware_routing_window_days_past`
  - `operator_settings.extra.reservation_aware_routing_window_days_future`
- settings are clamped to safe bounds before use
- 60-second in-process cache prevents duplicate lookup bursts

## Observability

The route decision appends parser-note metadata to `message_normalizations`:

- `lifecycle_routing_source`
- `pms_match_method`
- `reservation_id`
- `reservation_check_in`
- `reservation_check_out`
- `lifecycle_resolved`

Non-match and degraded paths are also recorded through
`lifecycle_routing_source`, including:

- `concierge_session`
- `pms_reservation_matched`
- `no_match_pre_booking`
- `pms_lookup_disabled`
- `pms_lookup_failed`

## Exception Model

The PMS lookup path fails open:

- timeout, HTTP, credential, or schema issues log structured context
- lookup failures cache briefly to avoid repeated hammering
- routing falls back to the existing pre-booking path instead of failing closed

That preserves intake continuity while making the degraded path visible.
