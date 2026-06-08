import type { Decision, FeedUpdate } from "../types";

/*
  A realistic morning for a short-term-rental portfolio. The threads cross:
  the Okonkwos appear as both a soft-held rebooking (feed) and a discount
  question (decision); the Sandpiper thermostat I'm watching shows up next to
  a 30-day inquiry for the same unit; The Lookout has both a check-in and a
  late-checkout request. It should feel like one place, one morning, one
  employee keeping track of all of it.

  All copy is first-person — me speaking to Lanier.
*/

export const PORTFOLIO = {
  operator: "Lanier",
  propertyCount: 12,
  lastCheckIn: "2026-06-07T21:38:00",
};

export const FEED: FeedUpdate[] = [
  {
    kind: "update",
    id: "u-marlowe-checkout",
    channel: "email",
    at: "2026-06-08T09:18:00",
    tag: "checkin",
    property: "The Lookout",
    guest: "The Marlowe party",
    summary:
      "Sent the Marlowes their checkout steps for tomorrow and asked how the stay went. They mentioned the coffee maker was temperamental — I've flagged it for the turnover crew.",
    reasoning: {
      observed: [
        { label: "Checkout", value: "Tomorrow, 11:00 AM" },
        { label: "Stay length", value: "6 nights" },
        { label: "Open issues", value: "None during stay" },
      ],
      thought:
        "They're a day from checkout and hadn't heard the routine, so I sent it early — checkout's smoother when it isn't a surprise. When they replied about the coffee maker I didn't want it to vanish into an email thread, so I turned it into a turnover note tied to the unit rather than asking you to remember it.",
    },
    decision:
      "Send checkout instructions now, and convert any stay feedback into a turnover note instead of a to-do for you.",
    outcome:
      "Checkout email delivered. Coffee maker logged for the turnover crew to check before the next guest.",
    draft: {
      channel: "email",
      to: "The Marlowe party",
      subject: "Checking out of The Lookout — a few quick notes",
      sent: true,
      body: "Hi Dana — hard to believe it's already your last night. Checkout is any time before 11 AM tomorrow; there's nothing to clean, just drop the keys in the lockbox and pull the door firmly behind you. If it's easy, I'd love to hear how the stay treated you. Thanks for being such easy guests to host.",
    },
  },
  {
    kind: "update",
    id: "u-poolheat-jordan",
    channel: "text",
    at: "2026-06-08T08:54:00",
    tag: "handled",
    property: "Beach House",
    guest: "Jordan Lee",
    summary:
      "Jordan asked if the pool would be heated for their October stay. I confirmed it can be — $45/night — and offered to add it. They said yes, so it's noted for the turnover team.",
    reasoning: {
      observed: [
        { label: "Asked", value: "Is the pool heated in October?" },
        { label: "Property fact", value: "Pool heat available · $45/night" },
        { label: "Stay", value: "Oct 14–19 · 5 nights" },
        { label: "Confidence", value: "94% — clear property match" },
      ],
      thought:
        "This one I know cold — the Beach House pool can be heated and the rate is documented, so there was no reason to make Jordan wait on a human. October gulf water is cool enough that the question usually means yes, so I confirmed and offered to add it in the same breath rather than making them ask twice.",
    },
    decision:
      "Answer directly and offer to add pool heat to the reservation — a documented amenity at a known price is squarely inside what I can handle.",
    outcome:
      "Jordan accepted. Pool heat noted on the reservation for the turnover team to enable before arrival.",
    draft: {
      channel: "text",
      to: "Jordan Lee",
      sent: true,
      body: "Hi Jordan — yes, the pool can be heated for your October stay. It runs $45/night and I can have it warm for your arrival on the 14th. Want me to add it? Happy to take care of it now.",
    },
  },
  {
    kind: "update",
    id: "u-lookout-checkin",
    governedBy: ["seed-checkin-timing"],
    channel: "email",
    at: "2026-06-08T08:40:00",
    tag: "checkin",
    property: "The Lookout",
    guest: "The Henderson family",
    summary:
      "Sent the Hendersons their check-in details for this evening — door code, parking, and wifi. Their flight lands at 3 and the house is ready at 4, so the timing lines up.",
    reasoning: {
      observed: [
        { label: "Check-in", value: "Today, from 4:00 PM" },
        { label: "Flight arrival", value: "3:05 PM (from itinerary)" },
        { label: "Turnover", value: "Marked ready 7:20 AM" },
      ],
      thought:
        "The unit's already flipped and their flight gets in just before the house opens, so I sent everything now while they're still at the gate and have signal. I double-checked the turnover was marked ready before promising a 4 PM arrival — I don't send a check-in time I can't stand behind.",
    },
    decision:
      "Send full arrival details the morning of check-in, only after confirming the turnover is complete.",
    outcome: "Check-in email delivered. No questions back so far.",
    draft: {
      channel: "email",
      to: "The Henderson family",
      subject: "Everything you need for tonight at The Lookout",
      sent: true,
      body: "Hi Sarah — looking forward to hosting you this evening. The house is yours from 4 PM. Door code is 4-8-2-7 (tap the checkmark to lock). Park in the carport, either spot. Wifi is \"Lookout-Guest,\" password sunrise2026. I hope the flight in is smooth — text this number the moment anything comes up and I'll be right here.",
    },
  },
  {
    kind: "update",
    id: "u-smoke-battery",
    governedBy: ["seed-spend-cap"],
    channel: "voice",
    at: "2026-06-08T07:36:00",
    tag: "resolved",
    property: "Beach House",
    summary:
      "The Beach House smoke detector was chirping on a low battery. I called Coastal Handyman, who replaced it this morning. The guest never had to deal with it.",
    reasoning: {
      observed: [
        { label: "Signal", value: "Low-battery chirp reported 6:50 AM" },
        { label: "Guest on site", value: "Yes — checked in Friday" },
        { label: "Vendor", value: "Coastal Handyman · 9-min drive" },
        { label: "Cost", value: "$0 — covered under service plan" },
      ],
      thought:
        "A chirping detector at 7 AM is exactly the kind of small thing that sours a stay, and it was a battery, not a fire — low urgency, zero judgment needed. Coastal Handyman is on the service plan so there was no cost question, and they were nearby, so I just called and had it done before the guest was really up.",
    },
    decision:
      "Dispatch the on-plan handyman immediately — a known fix, a covered cost, no reason to wait or ask.",
    outcome:
      "Battery replaced at 7:28 AM. Detector confirmed working. Guest not disturbed.",
    draft: {
      channel: "voice",
      to: "Coastal Handyman (dispatch line)",
      sent: true,
      body: "Called to ask for a battery swap on the Beach House hallway smoke detector — it started chirping this morning and there's a family checked in. Confirmed it's covered under the service plan and gave the lockbox code. They headed over right away.",
    },
  },
  {
    kind: "update",
    id: "u-overnight-summary",
    channel: "text",
    at: "2026-06-08T06:12:00",
    tag: "handled",
    property: "Portfolio-wide",
    summary:
      "Answered 11 guest questions across the portfolio overnight — wifi passwords, a late-checkout ask I could grant, restaurant recommendations. All routine, all handled. None needed you.",
    reasoning: {
      observed: [
        { label: "Messages handled", value: "11, across 6 properties" },
        { label: "Topics", value: "Wifi, parking, dining, one late checkout" },
        { label: "Escalated", value: "0" },
        { label: "Avg. response", value: "Under 2 minutes" },
      ],
      thought:
        "Overnight is mostly the same handful of questions, and I have all the answers documented, so I just kept up with them. The one late-checkout request was for a unit with no same-day arrival, so granting it was free — I said yes without waking anyone. I'm only summarizing these so you know the night was quiet, not so you have to do anything.",
    },
    decision:
      "Handle routine overnight questions directly and roll them into a single morning summary rather than 11 separate pings.",
    outcome: "All 11 resolved overnight. Nothing carried over to your morning.",
  },
  {
    kind: "update",
    id: "u-plumber-pelican",
    governedBy: ["seed-spend-cap"],
    channel: "voice",
    at: "2026-06-08T03:48:00",
    tag: "resolved",
    property: "Pelican Perch",
    guest: "Unit 4B guest",
    summary:
      "The guest at Pelican Perch 4B flagged a slow-draining kitchen sink twice tonight. I reached the after-hours plumber, who's confirmed for 8 AM, and let the guest know they'll have access through the lockbox.",
    reasoning: {
      observed: [
        { label: "Reported", value: "Twice — 11:40 PM and 1:15 AM" },
        { label: "Severity", value: "Slow drain, not a leak or overflow" },
        { label: "Vendor", value: "Rivera Plumbing · after-hours line" },
        { label: "Quoted", value: "$140 call-out — within auto-approve" },
      ],
      thought:
        "They mentioned it twice, which tells me it's bothering them even though it's not an emergency — no water on the floor, nothing that can't wait until morning. A 2 AM visit would disturb the whole building for a slow drain, so I booked the first morning slot instead. The $140 call-out is under your $500 limit, so I confirmed it rather than holding it for you.",
    },
    decision:
      "Book the first morning slot with the on-call plumber, not an overnight emergency visit, and keep the guest informed so they feel heard.",
    outcome:
      "Rivera confirmed for 8:00 AM. Guest acknowledged and seemed satisfied it's handled.",
    draft: {
      channel: "voice",
      to: "Rivera Plumbing (after-hours)",
      sent: true,
      body: "Called the after-hours line about a slow kitchen drain at Pelican Perch, unit 4B — guest is here but it's not urgent, no leak. Asked for the first morning slot rather than a callout tonight. Confirmed 8 AM and passed along the lockbox code and the guest's name.",
    },
  },
  {
    kind: "update",
    id: "u-okonkwo-rebook",
    channel: "email",
    at: "2026-06-08T02:05:00",
    tag: "booking",
    property: "Dauphin Cottage",
    guest: "The Okonkwo family",
    summary:
      "The Okonkwos wrote in about rebooking Dauphin Cottage for Thanksgiving week. They stayed twice last year, both 5-star. I sent the available dates and put a soft 24-hour hold on the unit.",
    reasoning: {
      observed: [
        { label: "Guest history", value: "2 prior stays · two 5-star reviews" },
        { label: "Requested", value: "Thanksgiving week · Nov 24–29" },
        { label: "Availability", value: "Open — no conflicts" },
        { label: "Note", value: "They asked about their returning-guest rate" },
      ],
      thought:
        "Repeat guests this good are worth moving quickly for, and the week is wide open, so I sent the dates and softly held the unit so it can't slip away while they decide. They also asked for the returning-guest rate they had last year — that's a pricing call I can't make on my own, so I've left it open and surfaced it to you separately rather than quoting a discount I'm not authorized to give.",
    },
    decision:
      "Confirm availability and protect the dates with a soft hold, but stop short of pricing — the discount question goes to you.",
    outcome:
      "Dates sent, unit softly held for 24 hours. The rate question is waiting for you in Needs Your Input.",
    draft: {
      channel: "email",
      to: "The Okonkwo family",
      subject: "We'd love to have you back for Thanksgiving",
      sent: true,
      body: "Hi Amara — so lovely to hear from you. Dauphin Cottage is open for Thanksgiving week (the 24th through the 29th) and I've held it for you for the next day so it doesn't get booked out from under you. I saw your note about your returning-guest rate — let me get that confirmed and come right back to you. We'd genuinely love to host your family again.",
    },
  },
  {
    kind: "update",
    id: "u-sandpiper-thermostat",
    channel: "text",
    at: "2026-06-08T01:20:00",
    tag: "noticed",
    property: "Sandpiper Suite",
    summary:
      "Heads up — the Sandpiper Suite thermostat has read 78°F for six hours with no guest on site. Could be a stuck sensor, could be someone left it running. I haven't acted; I'm just watching it.",
    reasoning: {
      observed: [
        { label: "Reading", value: "78°F, steady for 6 hours" },
        { label: "Occupancy", value: "Vacant — next guest not until the 11th" },
        { label: "Last turnover", value: "June 5" },
        { label: "Energy impact", value: "Minor so far" },
      ],
      thought:
        "Nothing here is urgent — the unit's empty and a few degrees costs pennies, so dispatching someone at 1 AM would be an overreaction. But a thermostat that won't move can be an early sign of a sensor going, and I'd rather mention it now than have you discover it on turnover day. I'm leaving it as something I've noticed, not something I've acted on.",
    },
    decision:
      "Watch and report, don't dispatch. Too minor to act on overnight, too worth-knowing to stay silent.",
    outcome:
      "Still monitoring. I'll fold a sensor check into the next scheduled turnover unless it changes.",
  },
];

export const DECISIONS: Decision[] = [
  {
    kind: "decision",
    id: "d-ac-beachhouse",
    governedBy: ["seed-spend-cap"],
    channel: "voice",
    at: "2026-06-08T09:26:00",
    priority: "high",
    property: "Beach House",
    guest: "The Castellano family",
    ask: "The Beach House AC is fully out and it's 91°F — do I send the emergency tech, or move the family?",
    briefLine: "the Beach House AC is out in a heat advisory with two young kids on site",
    detail:
      "Two kids on site. The emergency repair is $850, which is over your $500 auto-approve limit, so I stopped to ask.",
    reasoning: {
      observed: [
        { label: "Status", value: "AC not cooling — confirmed, not a thermostat" },
        { label: "Outside", value: "91°F, heat advisory until 7 PM" },
        { label: "Guests", value: "Family of 4, two children under 10" },
        { label: "Emergency repair", value: "$850 — exceeds your $500 limit" },
        { label: "Alternative", value: "Pelican Perch is open all week" },
      ],
      thought:
        "This one's genuinely urgent — a failed AC in a heat advisory with young kids isn't something to leave sitting, and the family has already texted once. I can have an emergency tech there within the hour, but the quote is $850 and your auto-approve stops at $500, so I won't spend it without your word. The clean alternative is moving them to Pelican Perch, which is open all week and a slightly nicer unit — that turns a complaint into a save, but it's a bigger gesture and I didn't want to offer a move you hadn't sanctioned. Both paths are ready; I just need you to point.",
    },
    proposal:
      "My lean is to send the emergency tech now and keep them in place — it's the smaller cost and least disruption if the fix holds. If you'd rather not gamble on the repair, I'll move them to Pelican Perch and comp the difference.",
    draft: {
      channel: "text",
      to: "The Castellano family",
      sent: false,
      body: "Hi Marisol — I'm so sorry about the AC, especially in this heat. I've got a technician who can be there within the hour to fix it, and I'm sending a couple of fans over in the meantime. If you'd prefer, I can also move you to a comparable place nearby that's cool and ready right now — whichever you'd like. I'll stay on this until you're comfortable.",
    },
    options: [
      {
        id: "send-tech",
        label: "Send the emergency tech ($850)",
        kind: "approve",
        resultSummary:
          "You approved the $850 emergency AC repair at Beach House. I've dispatched the tech for within the hour and let the Castellanos know help is on the way, with fans en route in the meantime.",
      },
      {
        id: "move-guest",
        label: "Move them to Pelican Perch",
        kind: "alternative",
        resultSummary:
          "You chose to relocate the Castellanos to Pelican Perch. I've offered them the move, comped the difference, and I'm arranging help with their bags. I'll schedule the Beach House AC repair at a normal rate.",
      },
      {
        id: "hold-ac",
        label: "Hold — I'll call them myself",
        kind: "decline",
        resultSummary:
          "Holding the Beach House AC decision for you. I've let the Castellanos know you'll be in touch shortly and sent fans over to keep them comfortable in the meantime.",
      },
    ],
  },
  {
    kind: "decision",
    id: "d-refund-dauphin",
    channel: "email",
    at: "2026-06-08T08:11:00",
    priority: "high",
    property: "Dauphin Cottage",
    guest: "Mr. Pearson",
    ask: "A guest wants a full refund after one night over 'cleanliness,' but the check-in photos look clean to me. How do you want to play it?",
    briefLine: "a guest is asking for a full refund I don’t think is fair",
    detail:
      "It's a money decision with conflicting evidence, so I haven't replied. The turnover was photo-verified clean 90 minutes before check-in.",
    reasoning: {
      observed: [
        { label: "Request", value: "Full refund — $1,180 — after 1 of 4 nights" },
        { label: "Stated reason", value: "\"Unclean on arrival\"" },
        { label: "Turnover", value: "Photo-verified clean, 90 min before check-in" },
        { label: "Specifics given", value: "None yet — no photos, no detail" },
        { label: "Guest history", value: "First stay, no prior record" },
      ],
      thought:
        "I'm genuinely torn, which is why it's with you. The turnover crew's timestamped photos show a clean unit 90 minutes before arrival, and the guest hasn't pointed to anything specific — that pattern sometimes means buyer's remorse dressed up as a complaint. But I can't see what they saw, and getting a cleanliness call wrong publicly is expensive in reviews. This is money and judgment in the same decision, so I don't think it's mine to make. I'd suggest asking for specifics before any refund, but I didn't want to send even that without you, in case you'd rather just refund and protect the rating.",
    },
    proposal:
      "I'd reply warmly and ask for photos or specifics before deciding on any refund — that's usually enough to tell a real issue from remorse, and it doesn't commit us either way. Say the word and I'll send it.",
    draft: {
      channel: "email",
      to: "Mr. Pearson",
      subject: "Re: My stay at Dauphin Cottage",
      sent: false,
      body: "Hi James — I'm sorry the cottage didn't meet your expectations on arrival; that's not the standard we hold. So I can make it right, could you send a photo or two of what you found? Our team flips the unit the morning of arrival, and I want to understand exactly what slipped through so we can address it properly for you.",
    },
    options: [
      {
        id: "ask-specifics",
        label: "Ask for specifics first",
        kind: "approve",
        resultSummary:
          "You okayed asking for specifics before any refund. I've emailed Mr. Pearson warmly requesting photos of the cleanliness issues, and I'll bring you his reply before going further.",
      },
      {
        id: "refund-full",
        label: "Refund in full, protect the review",
        kind: "alternative",
        resultSummary:
          "You chose to refund Mr. Pearson in full to protect the rating. I've processed the $1,180 refund and sent a gracious note inviting him to give us another try.",
      },
      {
        id: "decline-refund",
        label: "Decline — turnover was verified",
        kind: "decline",
        resultSummary:
          "You declined the refund on the strength of the verified turnover. I've let Mr. Pearson know politely, shared that the unit was inspected and photographed clean before arrival, and offered a fresh-linens visit to reset the stay.",
      },
    ],
  },
  {
    kind: "decision",
    id: "d-okonkwo-discount",
    governedBy: ["seed-returning-discount"],
    channel: "text",
    at: "2026-06-08T07:58:00",
    priority: "medium",
    property: "Dauphin Cottage",
    guest: "The Okonkwo family",
    ask: "The Okonkwos want their returning-guest rate for Thanksgiving — about 15% off. That's not in current policy. Approve it?",
    detail:
      "Two prior 5-star stays. I've softly held the unit, but I can't quote a discount you haven't set.",
    reasoning: {
      observed: [
        { label: "Requested", value: "~15% off — the rate they had last year" },
        { label: "Current policy", value: "No standing returning-guest discount" },
        { label: "Guest value", value: "2 stays · two 5-star reviews · ~$3,400 booked" },
        { label: "Dates", value: "Thanksgiving week — high demand" },
        { label: "Hold expires", value: "Tomorrow, 2:05 AM" },
      ],
      thought:
        "They're close to ideal guests, and 15% off a holiday week they'd reliably fill is an easy trade for the loyalty — most operators would take it. But there's no returning-guest discount on the books right now, so honoring last year's rate is a real pricing decision, and it sets a small precedent I shouldn't set for you. The hold buys us until tomorrow, so there's no rush; I just need a yes, a counter, or a no.",
    },
    proposal:
      "I'd approve the 15% for them — the lifetime value clears the discount easily. If you'd rather, I can counter at 10% or hold firm and frame it warmly so the relationship survives the no.",
    draft: {
      channel: "text",
      to: "The Okonkwo family",
      sent: false,
      body: "Amara — good news: I'd be glad to honor your returning-guest rate again for Thanksgiving week. I've kept the cottage held for you. Want me to lock it in at that rate now?",
    },
    options: [
      {
        id: "approve-15",
        label: "Approve the 15%",
        kind: "approve",
        resultSummary:
          "You approved the 15% returning-guest rate for the Okonkwos. I've confirmed it, locked in Thanksgiving week at Dauphin Cottage, and turned the soft hold into a booking.",
      },
      {
        id: "counter-10",
        label: "Counter at 10%",
        kind: "alternative",
        resultSummary:
          "You countered at 10% for the Okonkwos. I've offered it warmly as a returning-guest thank-you and kept the hold in place while they consider it.",
      },
      {
        id: "hold-rate",
        label: "Hold standard pricing",
        kind: "decline",
        resultSummary:
          "You're holding standard pricing for the Okonkwos. I've let them know gently, emphasized how glad we'd be to host them again, and kept the dates open for now.",
      },
    ],
  },
  {
    kind: "decision",
    id: "d-late-checkout-lookout",
    channel: "text",
    at: "2026-06-08T09:03:00",
    priority: "medium",
    property: "The Lookout",
    guest: "The Marlowe party",
    ask: "The Marlowes want a 2 PM late checkout tomorrow, but the next guest arrives at 4 and turnover usually takes three hours. Approve and rush it, or decline?",
    detail:
      "It's tight, not impossible. Same unit as tonight's check-in — the Hendersons are this evening, the next arrival is the day after.",
    reasoning: {
      observed: [
        { label: "Requested", value: "2:00 PM checkout (standard is 11 AM)" },
        { label: "Next arrival", value: "4:00 PM same day" },
        { label: "Turnover needed", value: "~3 hours" },
        { label: "Math", value: "2 PM out leaves a 2-hour flip — tight" },
        { label: "Cleaner", value: "Available, hasn't confirmed a rush" },
      ],
      thought:
        "A 2 PM checkout against a 4 PM arrival leaves two hours for a three-hour job, so saying yes means asking the cleaner to genuinely hustle and accepting some risk the next guest waits. The Marlowes have been lovely and I'd like to give them the win, but I won't promise a turnaround I'm not sure we can hit. A noon compromise is the honest middle — a little extra time for them without gambling the next check-in. I didn't want to pick for you when it's a real tradeoff.",
    },
    proposal:
      "I'd offer noon as a friendly compromise rather than a hard yes or no — it's the version I'm confident we can actually deliver. If the cleaner confirms a rush, I'll happily grant the full 2 PM.",
    draft: {
      channel: "text",
      to: "The Marlowe party",
      sent: false,
      body: "Hi Dana — I'd love to give you a slow morning. We've got a guest arriving right after you, so 2 PM is tough to promise, but I can comfortably offer noon. Would that extra hour help? If our cleaner can swing it, I'll stretch it further and let you know.",
    },
    options: [
      {
        id: "offer-noon",
        label: "Offer noon as the compromise",
        kind: "approve",
        resultSummary:
          "You went with the noon compromise for the Marlowes. I've offered it warmly and let them know I'll try to stretch it further if the cleaner can rush the flip.",
      },
      {
        id: "grant-2pm",
        label: "Grant 2 PM, rush the cleaner",
        kind: "alternative",
        resultSummary:
          "You granted the full 2 PM checkout. I've confirmed it with the Marlowes and asked the cleaner to prioritize a rush flip so the 4 PM arrival still lands on time.",
      },
      {
        id: "decline-late",
        label: "Hold the 11 AM checkout",
        kind: "decline",
        resultSummary:
          "You're holding the standard 11 AM checkout. I've let the Marlowes know kindly, framed it around getting the next guests a clean home on time, and offered a luggage hold if they want to stay in the area.",
      },
    ],
  },
  {
    kind: "decision",
    id: "d-monthly-sandpiper",
    channel: "email",
    at: "2026-06-08T06:40:00",
    priority: "low",
    property: "Sandpiper Suite",
    guest: "Priya Raman",
    ask: "An inquiry came in for a 30-day stay at the Sandpiper Suite. We've never done a monthly booking and there's no long-stay rate. Want me to quote it, and at what rate?",
    detail:
      "No rush — it's for September. It's a new scenario for us, so I'm not improvising a number.",
    reasoning: {
      observed: [
        { label: "Requested", value: "30 nights · Sept 2–Oct 1" },
        { label: "Nightly rate", value: "$210 — would be $6,300 at full price" },
        { label: "Precedent", value: "No prior monthly bookings" },
        { label: "Long-stay rate", value: "Not set" },
        { label: "Typical market", value: "Monthly stays often discount 20–30%" },
      ],
      thought:
        "A 30-day booking is a different animal than a weekend — lower turnover cost, steadier income, but the market usually expects a monthly discount, and we've never set one. I could quote full rate, but that likely loses it, and quoting a discount means inventing pricing policy, which is yours to set, not mine. There's no time pressure since it's September, so the right move is to ask rather than guess. Once you tell me the long-stay approach, I'll handle every monthly inquiry like this on my own going forward.",
    },
    proposal:
      "I'd suggest quoting around 20% off for the month — competitive without underselling. Give me a number or a rule and I'll reply, and I'll reuse it for future long-stay inquiries.",
    draft: {
      channel: "email",
      to: "Priya Raman",
      subject: "Re: Monthly stay at the Sandpiper Suite",
      sent: false,
      body: "Hi Priya — thank you for thinking of the Sandpiper Suite for September. A full month sounds wonderful. Let me put together a monthly rate for you and come right back with the details — I want to make a longer stay genuinely worth your while.",
    },
    options: [
      {
        id: "quote-20",
        label: "Quote 20% off for the month",
        kind: "approve",
        resultSummary:
          "You set the monthly rate at 20% off. I've quoted Priya $5,040 for the 30 nights and saved this as our long-stay rule, so I'll handle future monthly inquiries without asking.",
      },
      {
        id: "quote-full",
        label: "Quote full rate",
        kind: "alternative",
        resultSummary:
          "You chose to quote full rate. I've sent Priya the standard $6,300 for the month, framed around the value of the space, and noted no long-stay discount is in effect.",
      },
      {
        id: "decline-monthly",
        label: "We don't do monthly stays",
        kind: "decline",
        resultSummary:
          "You'd rather not take monthly bookings. I've let Priya down gently, explained we host shorter stays, and noted the policy so I can answer the next long-stay inquiry directly.",
      },
    ],
  },
];
