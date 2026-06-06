import test from "node:test";
import assert from "node:assert/strict";

import { classifyForToday } from "../../shared/lifecycle/windows";
import { derivePriorityCard } from "./priorityRules";

const NOW = new Date(Date.UTC(2026, 4, 28, 12, 0, 0));

function dateFromNow(daysFromToday: number): string {
  const date = new Date(Date.UTC(2026, 4, 28 + daysFromToday));
  return date.toISOString().slice(0, 10);
}

function makeSession(overrides: Record<string, unknown> = {}) {
  return {
    sessionId: "sess_test",
    token: "tok_test",
    guestName: "Test Guest",
    guestPhone: "",
    guestEmail: "",
    propertyCode: "BH-1",
    propertyName: "Beach House",
    numGuests: 2,
    checkIn: null,
    checkOut: null,
    status: "active",
    phase: "",
    conversationCount: 0,
    lastMessageAt: null,
    openEscalations: 0,
    reservationId: "",
    pmsSyncedAt: null,
    proactiveTriggeredAt: null,
    hasBookingContext: true,
    journeyTracked: false,
    welcomeSent: false,
    checkinReminderSent: false,
    checkoutReminderSent: false,
    extendOfferSent: false,
    poolHeatOffered: false,
    poolHeatAccepted: false,
    notificationsSent: 0,
    assignedOperatorId: "",
    assignedOperatorLabel: "",
    openHandoffCount: 0,
    assignmentStatus: "unassigned",
    workflow: {},
    ...overrides,
  };
}

test("classifyForToday: exactly 7 days out lands in arriving", () => {
  const classification = classifyForToday(
    {
      checkIn: dateFromNow(7),
      checkOut: dateFromNow(10),
    },
    NOW,
  );
  assert.equal(classification.bucket, "arriving");
  assert.equal(classification.daysUntilCheckIn, 7);
});

test("classifyForToday: exactly 8 days out lands in pre_arrival", () => {
  const classification = classifyForToday(
    {
      checkIn: dateFromNow(8),
      checkOut: dateFromNow(12),
    },
    NOW,
  );
  assert.equal(classification.bucket, "pre_arrival");
  assert.equal(classification.daysUntilCheckIn, 8);
});

test("classifyForToday: check-in day lands in in_stay", () => {
  const classification = classifyForToday(
    {
      checkIn: dateFromNow(0),
      checkOut: dateFromNow(3),
    },
    NOW,
  );
  assert.equal(classification.bucket, "in_stay");
});

test("classifyForToday: checkout day stays in in_stay", () => {
  const classification = classifyForToday(
    {
      checkIn: dateFromNow(-3),
      checkOut: dateFromNow(0),
    },
    NOW,
  );
  assert.equal(classification.bucket, "in_stay");
});

test("classifyForToday: day after checkout lands in post_stay", () => {
  const classification = classifyForToday(
    {
      checkIn: dateFromNow(-4),
      checkOut: dateFromNow(-1),
    },
    NOW,
  );
  assert.equal(classification.bucket, "post_stay");
  assert.equal(classification.daysSinceCheckOut, 1);
});

test("classifyForToday: phase in_stay overrides date math", () => {
  const classification = classifyForToday(
    {
      phase: "in_stay",
      checkIn: dateFromNow(3),
      checkOut: dateFromNow(5),
    },
    NOW,
  );
  assert.equal(classification.bucket, "in_stay");
});

test("derivePriorityCard: 30-day pre_arrival guest does not get imminent welcome prompt", () => {
  const session = makeSession({
    checkIn: dateFromNow(30),
    checkOut: dateFromNow(34),
  });
  const classification = classifyForToday(session, NOW);
  const priorityCard = derivePriorityCard(session as never, classification, null);
  assert.notEqual(classification.bucket, "arriving");
  assert.equal(priorityCard, null);
});

test("derivePriorityCard: 2-day arriving guest gets imminent welcome prompt", () => {
  const session = makeSession({
    checkIn: dateFromNow(2),
    checkOut: dateFromNow(5),
  });
  const classification = classifyForToday(session, NOW);
  const priorityCard = derivePriorityCard(session as never, classification, null);
  assert.equal(classification.bucket, "arriving");
  assert.deepEqual(priorityCard, {
    label: "Welcome not sent · arrives in 2 days",
    tone: "warning",
  });
});
