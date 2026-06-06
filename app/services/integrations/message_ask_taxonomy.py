from __future__ import annotations

import re


_BASE_ASK_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "neighborhood": (
        re.compile(r"\b(neighborhood|community|area|located|location)\b", re.I),
        re.compile(r"\b(seagrove|seaside|rosemary|watercolor|alys|grayton|dune allen|santa rosa|miramar)\b", re.I),
        re.compile(r"\bpart of\b.*\b(community|area|neighborhood)\b", re.I),
    ),
    "pool_access": (
        re.compile(r"\bpool[s]?\b", re.I),
        re.compile(r"\bswim(ming)?\b", re.I),
        re.compile(r"\bhot tub|jacuzzi|spa\b", re.I),
    ),
    "beach_access": (
        re.compile(r"\bbeach\b", re.I),
        re.compile(r"\bshoreline|sand|ocean|gulf\b", re.I),
        re.compile(r"\bbeach (access|service|concierge|chair|umbrella|setup)\b", re.I),
    ),
    "beach_service": (
        re.compile(r"\bbeach chairs?\b", re.I),
        re.compile(r"\bumbrellas?\b", re.I),
        re.compile(r"\bbeach service\b", re.I),
        re.compile(r"\bchair setup\b", re.I),
    ),
    "amenities": (
        re.compile(r"\bamenit(y|ies)\b", re.I),
        re.compile(r"\b(wifi|wi-fi|internet)\b", re.I),
        re.compile(r"\b(grill|bbq|fire pit|outdoor kitchen)\b", re.I),
        re.compile(r"\b(kayak|paddle|bike|cruiser)\b", re.I),
    ),
    "wifi_issue": (
        re.compile(r"\b(wifi|wi-fi|internet)\b", re.I),
        re.compile(r"\b(out|down|offline|not working|never got .* back)\b", re.I),
        re.compile(r"\b(no internet|internet has been out|internet .* out all day)\b", re.I),
    ),
    "pest_issue": (
        re.compile(r"\b(cock ?roach(?:es)?|roach(?:es)?|bug(?:s)?|pest(?:s)?)\b", re.I),
        re.compile(r"\bin the kitchen\b", re.I),
    ),
    "service_issue": (
        re.compile(r"\b(not working|broken|out all day|never got .* back)\b", re.I),
        re.compile(r"\bvery frustrating\b", re.I),
        re.compile(r"\bissue(?:s)? during our stay\b", re.I),
        re.compile(r"\bproblem(?:s)? during our stay\b", re.I),
    ),
    "refund_request": (
        re.compile(r"\brefund\b", re.I),
        re.compile(r"\bsmall refund\b", re.I),
        re.compile(r"\bcompensation\b", re.I),
        re.compile(r"\bcredit(?: back)?\b", re.I),
        re.compile(r"\bcan anything be offered\b", re.I),
    ),
    "refund_deadline": (
        re.compile(r"\bunable to refund\b", re.I),
        re.compile(r"\bafter [A-Za-z]+ \d{1,2}(?:th|st|nd|rd)?\b.*\brefund\b", re.I),
        re.compile(r"\bwithin the time frame to cancel\b", re.I),
        re.compile(r"\brefund window\b", re.I),
    ),
    "service_recovery": (
        re.compile(r"\bplease let me know if\b.*\brefund\b", re.I),
        re.compile(r"\bvery frustrating\b", re.I),
        re.compile(r"\b(remote|work remote)\b", re.I),
        re.compile(r"\bcouldn[’']t wind down\b", re.I),
        re.compile(r"\bduring our stay\b", re.I),
    ),
    "sleeping_arrangement": (
        re.compile(r"\b(bed|beds|bedroom|bedrooms|sleep|sleeps|accommodate|accommodation)\b", re.I),
        re.compile(r"\b(king|queen|twin|bunk|sofa bed|pullout)\b", re.I),
    ),
    "pet_policy": (
        re.compile(r"\b(pet[s]?|dog[s]?|cat[s]?|animal[s]?)\b", re.I),
        re.compile(r"\bpet[- ]friendly\b", re.I),
    ),
    "service_animal_policy": (
        re.compile(r"\bservice animal[s]?\b", re.I),
        re.compile(r"\bservice dog[s]?\b", re.I),
        re.compile(r"\bada\b", re.I),
        re.compile(r"\bassistance animal[s]?\b", re.I),
    ),
    "parking": (
        re.compile(r"\bpark(ing|ed)\b", re.I),
        re.compile(r"\bgarage|driveway|car\b", re.I),
    ),
    "check_in_process": (
        re.compile(r"\bcheck[- ]?in\b", re.I),
        re.compile(r"\bchecking in\b", re.I),
        re.compile(r"\barriv(al|ing|e)\b", re.I),
        re.compile(r"\bkey|code|lockbox\b", re.I),
    ),
    "early_check_in": (
        re.compile(r"\bearly check[- ]?in\b", re.I),
        re.compile(r"\barrive early\b", re.I),
        re.compile(r"\bcome earlier\b", re.I),
        re.compile(r"\bdrop bags early\b", re.I),
        re.compile(r"\bcheck in at\s+\d", re.I),
    ),
    "late_checkout": (
        re.compile(r"\blate check[- ]?out\b", re.I),
        re.compile(r"\bcheck[- ]?out times? (?:are )?flexible\b", re.I),
        re.compile(r"\bcheck out at\s+\d", re.I),
        re.compile(r"\bleave later\b", re.I),
        re.compile(r"\blater check[- ]?out\b", re.I),
        re.compile(r"\blater checkout\b", re.I),
    ),
    "pricing": (
        re.compile(r"\b(price|cost|rate|fee|deposit|discount)\b", re.I),
        re.compile(r"\$", re.I),
        re.compile(r"\bgive you\s+\$?\d[\d,]*(?:\.\d{2})?\b", re.I),
        re.compile(r"\bwould you take\s+\$?\d[\d,]*(?:\.\d{2})?\b", re.I),
        re.compile(r"\bcan you do\s+\$?\d[\d,]*(?:\.\d{2})?\b", re.I),
    ),
    "pricing_change": (
        re.compile(r"\b(total|price|rate).{0,40}\bincrease(?:d)?\b", re.I),
        re.compile(r"\bincrease within\s+\d+\s+hours?\b", re.I),
        re.compile(r"\bdid something happen to make it increase\b", re.I),
        re.compile(r"\bprice changed\b", re.I),
    ),
    "pricing_negotiation": (
        re.compile(r"\bi(?:\s*['’]ll|\s+will)\s+give you\s+\$?\d[\d,]*(?:\.\d{2})?\b", re.I),
        re.compile(r"\bwould you take\s+\$?\d[\d,]*(?:\.\d{2})?\b", re.I),
        re.compile(r"\bcan you do\s+\$?\d[\d,]*(?:\.\d{2})?\b", re.I),
        re.compile(r"\bwould you accept\s+\$?\d[\d,]*(?:\.\d{2})?\b", re.I),
        re.compile(r"\bwould you be willing to offer a discount\b", re.I),
        re.compile(r"\boutside our budget\b", re.I),
        re.compile(r"\bcounter(?:offer)?\b", re.I),
        re.compile(r"\bnegotiat(?:e|ion)\b", re.I),
    ),
    "promo_code_issue": (
        re.compile(r"\bpromo code\b", re.I),
        re.compile(r"\bdiscount code\b", re.I),
        re.compile(r"\bcode did not work\b", re.I),
        re.compile(r"\bcode doesn[’']t work\b", re.I),
        re.compile(r"\bstill the same price\b", re.I),
        re.compile(r"\bdiscount(?:ed)? total\b", re.I),
    ),
    "discount_condition": (
        re.compile(r"\bfor this stay\b", re.I),
        re.compile(r"\bwhen booking this weekend\b", re.I),
        re.compile(r"\bnightly rate\b", re.I),
        re.compile(r"\bwith discount code applied\b", re.I),
    ),
    "billing_or_payment": (
        re.compile(r"\bcredit card\b", re.I),
        re.compile(r"\bcharge(?:d)?\b", re.I),
        re.compile(r"\bpayment\b", re.I),
        re.compile(r"\bposted to my card\b", re.I),
        re.compile(r"\bpayout\b", re.I),
    ),
    "payment_status": (
        re.compile(r"\bpayment (?:had|has) been made\b", re.I),
        re.compile(r"\bsubmit(?:ted)? payment\b", re.I),
        re.compile(r"\bfirst payment\b", re.I),
        re.compile(r"\bpayment confirmation\b", re.I),
        re.compile(r"\breceived the attached confirmation\b", re.I),
    ),
    "receipt_request": (
        re.compile(r"\bsend (?:me|us) a receipt\b", re.I),
        re.compile(r"\bneed a receipt\b", re.I),
        re.compile(r"\bpayment receipt\b", re.I),
        re.compile(r"\bconfirm our first payment\b", re.I),
    ),
    "agreement_completion": (
        re.compile(r"\brental agreement\b", re.I),
        re.compile(r"\byou signed\b", re.I),
        re.compile(r"\bsigned and submitted\b", re.I),
        re.compile(r"\bfinal agreement\b", re.I),
    ),
    "agreement_dispute": (
        re.compile(r"\bmodify the wording\b", re.I),
        re.compile(r"\bdelete(?:ion)? of the .*paragraph\b", re.I),
        re.compile(r"\bamend(?:ing)? the contract\b", re.I),
        re.compile(r"\brestatement providing the verbal assurance\b", re.I),
        re.compile(r"\bstandard rental agreement\b", re.I),
        re.compile(r"\bwon[’']t be amending the contract\b", re.I),
    ),
    "cancellation_request": (
        re.compile(r"\bcancellation request\b", re.I),
        re.compile(r"\basking to cancel\b", re.I),
        re.compile(r"\bcancel(?: the)? reservation\b", re.I),
        re.compile(r"\brequest to cancel\b", re.I),
    ),
    "reservation_change": (
        re.compile(r"\bmodify\b.*\breservation\b", re.I),
        re.compile(r"\bmodify\b.*\btrip\b", re.I),
        re.compile(r"\bchange(?:d)? my number of guests\b", re.I),
        re.compile(r"\bchange(?:d)? our dates\b", re.I),
        re.compile(r"\bcan this be booked for\b", re.I),
    ),
    "date_change_request": (
        re.compile(r"\bmodify our trip to\b", re.I),
        re.compile(r"\binstead of\b", re.I),
        re.compile(r"\bchange (?:our|my) trip to\b", re.I),
        re.compile(r"\bchange (?:our|my) dates to\b", re.I),
        re.compile(r"\bmove (?:our|my) stay to\b", re.I),
    ),
    "reservation_ops": (
        re.compile(r"\breservation id\b", re.I),
        re.compile(r"\bcancellation request\b", re.I),
        re.compile(r"\bcancel(?: the)? booking\b", re.I),
        re.compile(r"\basking to cancel a booking\b", re.I),
        re.compile(r"\bguest rental agreement\b", re.I),
        re.compile(r"\brefund\b", re.I),
        re.compile(r"\breceipt\b", re.I),
    ),
    "availability": (
        re.compile(r"\bavailabl(e|ility)\b", re.I),
        re.compile(r"\bopen\b.*\b(date|week|weekend)\b", re.I),
    ),
    "courtesy_hold": (
        re.compile(r"\bcourtesy hold\b", re.I),
        re.compile(r"\bhold this (?:home|property|place)\b", re.I),
        re.compile(r"\bhold (?:it|this|the home|the property).{0,20}\b(?:24 hours?|through|until)\b", re.I),
        re.compile(r"\bpossible to hold\b", re.I),
    ),
    "off_platform_booking_risk": (
        re.compile(r"\bbook directly\b", re.I),
        re.compile(r"\bthrough your company\b", re.I),
        re.compile(r"\bonly use (?:vrbo|airbnb) to book\b", re.I),
        re.compile(r"\btrying to avoid fees\b", re.I),
        re.compile(r"\bavoid fees\b", re.I),
        re.compile(r"\bbook through (?:here|vrbo|airbnb) or\b", re.I),
    ),
    "group_or_event": (
        re.compile(r"\b(wedding|reunion|group|party|event|celebration|engagement)\b", re.I),
        re.compile(r"\bbachelorette\b", re.I),
        re.compile(r"\bbachelor party\b", re.I),
    ),
    "event_policy": (
        re.compile(r"\b(engagement|wedding|reunion|party|event|celebration)\b", re.I),
        re.compile(r"\bis (this|that) allowed\b", re.I),
        re.compile(r"\ballowed at your place\b", re.I),
        re.compile(r"\bcan we celebrate\b", re.I),
    ),
    "occupancy_policy": (
        re.compile(r"\baccommodate[s]?\s+\d+\b", re.I),
        re.compile(r"\bsleeps?\s+\d+\b", re.I),
        re.compile(r"\bmax(?:imum)? occupancy\b", re.I),
        re.compile(r"\bhow many (people|guests)\b", re.I),
    ),
    "booking_eligibility": (
        re.compile(r"\brequirement for booking\b", re.I),
        re.compile(r"\bover 25\b", re.I),
        re.compile(r"\bunder 25\b", re.I),
        re.compile(r"\bminimum age\b", re.I),
        re.compile(r"\bbook with one of their names\b", re.I),
        re.compile(r"\bcould i do it through my\b", re.I),
    ),
    "house_rules": (
        re.compile(r"\b(is|are)\s+.*\s+allowed\b", re.I),
        re.compile(r"\bhouse rules?\b", re.I),
        re.compile(r"\brules?\b", re.I),
        re.compile(r"\bpolicy|policies\b", re.I),
    ),
    "amenity_inclusion": (
        re.compile(r"\bcomes? with the booking\b", re.I),
        re.compile(r"\bincluded with the booking\b", re.I),
        re.compile(r"\badditional fee\b", re.I),
        re.compile(r"\bcomes? with (?:the|this) stay\b", re.I),
    ),
    "access_entitlement": (
        re.compile(r"\bwristbands?\b", re.I),
        re.compile(r"\binclude access to\b", re.I),
        re.compile(r"\ballotted with (?:this|the) stay\b", re.I),
        re.compile(r"\bcamp watercolor\b", re.I),
        re.compile(r"\bbeach club\b", re.I),
    ),
    "local_vendor_recommendation": (
        re.compile(r"\bany recs\b", re.I),
        re.compile(r"\bwho for\b", re.I),
        re.compile(r"\bwho do you recommend\b", re.I),
        re.compile(r"\bhow to rent\b", re.I),
        re.compile(r"\brent / who\b", re.I),
    ),
    "bring_your_own_gear_policy": (
        re.compile(r"\bbring our own\b", re.I),
        re.compile(r"\bbring my own\b", re.I),
        re.compile(r"\bbring your own\b", re.I),
        re.compile(r"\ballowed to bring our own\b", re.I),
        re.compile(r"\ballowed to bring my own\b", re.I),
        re.compile(r"\bto (?:the )?beach\b", re.I),
    ),
    "accessibility": (
        re.compile(r"\b(wheelchair|accessib(le|ility)|mobility|stair|elevator)\b", re.I),
    ),
}

_MARKET_ASK_PATTERNS: dict[str, dict[str, tuple[re.Pattern[str], ...]]] = {
    "30a_fl": {
        "beach_service": (
            re.compile(r"\bbring our own beach chairs?\b", re.I),
            re.compile(r"\bbring our own umbrella\b", re.I),
        ),
    },
    "park_city_ut": {
        "ski_access": (
            re.compile(r"\bski[- ]in|ski[- ]out\b", re.I),
            re.compile(r"\blift tickets?\b", re.I),
            re.compile(r"\bchairlift\b", re.I),
            re.compile(r"\bslopes?\b", re.I),
            re.compile(r"\bski lockers?\b", re.I),
        ),
    },
}


def detect_message_asks(message_body: str, market_id: str = "") -> list[str]:
    if not message_body:
        return []
    hits: list[str] = []
    patterns_by_tag = dict(_BASE_ASK_PATTERNS)
    market_patterns = _MARKET_ASK_PATTERNS.get((market_id or "").strip().lower(), {})
    patterns_by_tag.update(market_patterns)
    for tag, patterns in patterns_by_tag.items():
        if any(p.search(message_body) for p in patterns):
            hits.append(tag)
    return hits
