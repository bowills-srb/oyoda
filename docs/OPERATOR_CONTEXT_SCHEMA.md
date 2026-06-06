# Operator Context Schema

## Purpose

This schema defines the minimum structured context Oyvoda should collect so
the brain can answer broadly, safely, and consistently across operators,
properties, markets, and seasons.

This is not a 30A-specific checklist. It is the national baseline for:

- reactive replies
- proactive outreach
- portfolio recommendations
- expert review / adversarial validation

## Why This Exists

Current live review shows the same failure mode repeatedly:

- the model can write fluent copy
- but it does not always have enough grounded truth to answer correctly
- operators often know the answer, but the system has not been given that
  answer in a durable, structured form

The goal is to stop solving this one email at a time and instead collect the
operator, property, portfolio, and market truth once so the brain can reason
over it repeatedly.

## Layer 1: Property Truth Pack

These fields should exist per property.

### Identity

- property name
- property code / external id
- full address
- lat/long
- operator portfolio id
- market
- submarket / neighborhood / community

### Capacity and Layout

- max guests
- max adults if applicable
- bedroom count
- bathroom count
- bed layout by room
- bunk-bed notes
- child-suitability notes
- occupancy constraints

### Amenities

- private pool
- pool heat available
- hot tub
- grill
- washer/dryer
- elevator
- parking count
- EV charging
- beach gear included
- bikes included and count
- golf cart included
- golf cart seat count
- golf cart add-on fee if applicable
- wifi network / password if allowed in operator-facing context

### Access and Arrival

- check-in time
- check-out time
- parking instructions
- entry method
- lock / key / lockbox / keypad notes
- building access notes
- luggage / early-arrival notes
- door code issuance policy

### Rules and Restrictions

- pet policy
- service animal handling guidance
- smoking policy
- quiet hours
- event / party policy
- age restrictions
- golf-cart allowed / not allowed / included / bring-your-own rules
- parking overflow rules

### Location and Nearby Context

- beach access type
- distance to beach
- walkability notes
- nearest grocery anchor
- nearest airport
- nearest town center / ski base / lake access / lift / shuttle
- seasonal access warnings

### Pricing-Relevant Facts

- minimum nights
- booking window restrictions
- direct-booking posture
- fee notes suitable for guest discussion
- whether discounts are ever considered at property level

## Layer 2: Portfolio Recommendation Pack

These fields should exist at the operator portfolio level.

### Matchable Filters

- which properties belong to the portfolio
- which properties are active / rentable
- available bedroom count
- available guest capacity
- pool / hot tub / golf cart flags
- neighborhood / community membership
- pet-friendly status
- elevator / accessibility tags
- family-friendly tags

### Recommendation Policy

- default number of recommendations to send
- maximum number of recommendations in first reply
- whether to ask guest to narrow before sending more
- whether to prioritize exact match over variety
- tie-break rules
- when to hold instead of recommend

### Availability Truth

- booking calendar source of truth
- freshness expectation
- availability confidence
- blackout sources
- hold rules for uncertain inventory

## Layer 3: Operator Policy Pack

These fields should exist at the operator level.

### Commercial Policy

- first-time renter discount policy
- negotiation allowed / not allowed
- direct-booking discount posture
- seasonality / demand sensitivity
- owner-approval thresholds

### Service Policy

- response tone
- signature preference
- whether to use brand name or operator name
- whether to omit generic closers
- liability-tone preference
- complaint language preference

### Escalation Policy

- legal / safety escalation triggers
- compensation/refund thresholds
- who reviews policy-sensitive topics
- always-review topics

### Accessibility and Compliance

- ADA-adjacent review-first topics
- service-animal handling policy
- fair-housing review-first topics

## Layer 4: Market and Seasonal Context Pack

These fields should exist at the market level so the core brain stays
location-agnostic.

### Market Profile

- market type: beach / ski / mountain / lake / city / desert / etc.
- relevant transport norms
- relevant amenity norms
- weather-sensitive considerations
- local terminology

### Seasonal Modifiers

- high / shoulder / low season timing
- winter-only constraints
- summer-only constraints
- weather-driven recommendation changes
- whether amenities are seasonal

### Place Intelligence

- grocery anchors
- dining districts
- coffee / family / nightlife / rainy-day categories
- travel-time context
- parking / shuttle / beach / lift access anchors

## Required Inference Layer

Not every operator will hand-enter all of this. The system should infer and
enrich where safe:

- geocode property address to lat/long
- derive market and submarket from address + operator mapping
- infer nearby anchors from geo/place context
- extract structured facts from guidebooks and uploaded docs
- normalize operator-authored rules into consistent policy fields

Inference should never silently override explicit operator truth.

## What Operators Should Upload

Operators should not be asked to fill a giant form from scratch if we already
have source material. The preferred intake order is:

1. Existing property guidebooks
2. PMS/listing exports
3. Existing FAQ / property notes
4. Portfolio inventory export
5. Operator policy questionnaire
6. Market-specific override questionnaire only where needed

## What Oyvoda Should Ask the Operator Explicitly

Only ask for the fields that are hard to infer or are operator-policy
dependent:

- discount posture
- negotiation posture
- golf-cart policy nuances
- complaint / liability tone
- escalation carve-outs
- recommendation strategy
- direct-booking posture
- accessibility review-first topics

## Minimum Launch Schema

If we need a fast path, these are the load-bearing fields:

- property address
- lat/long if already known
- neighborhood / community
- max guests
- bedroom count
- bed layout
- pool yes/no
- washer/dryer yes/no
- golf cart included / allowed / seat count
- pet policy
- parking summary
- beach / lift / town access summary
- first-time renter discount policy
- direct-booking posture
- recommendation count preference
- market type

## Current Gap to Close

Guidebooks likely already contain much of this truth, but the current
pre-booking context path does not guarantee that the full guidebook is being
used as structured grounding on every reply. That extraction and surfacing
layer needs to be upgraded in parallel with this schema.
