from __future__ import annotations


def needs_property_facts(message: str) -> bool:
    """Whether the message needs property-specific operational facts."""
    text = str(message or "").lower()
    return any(
        token in text
        for token in (
            "wifi",
            "wi-fi",
            "internet",
            "password",
            "door",
            "code",
            "lock",
            "check",
            "parking",
            "pool",
            "hot tub",
            "grill",
            "bikes",
            "bike",
            "beach gear",
            "kayak",
            "washer",
            "dryer",
            "trash",
            "towel",
            "pet",
            "dog",
            "cat",
            "quiet",
            "noise",
            "rule",
            "bbq",
            "propane",
        )
    )


def needs_nearby_availability(message: str) -> bool:
    """Whether the message suggests a nearby second-property search."""
    text = str(message or "").lower()
    people = any(
        token in text
        for token in (
            "friend",
            "friends",
            "couple",
            "family",
            "they",
            "them",
            "group",
            "another couple",
            "some people",
            "others",
            "people with us",
            "join us",
            "come down",
            "come too",
            "coming too",
            "travel with",
        )
    )
    availability = any(
        token in text
        for token in (
            "available",
            "availability",
            "stay close",
            "stay nearby",
            "near us",
            "close by",
            "same area",
            "same time",
            "same week",
            "same dates",
            "nearby",
            "next door",
            "down the street",
            "book",
            "rent",
            "place",
            "property",
            "house",
            "unit",
            "another",
        )
    )
    return people and availability


def needs_local_knowledge(message: str) -> bool:
    """Whether the message needs local recommendations / RAG context."""
    text = str(message or "").lower()
    return any(
        token in text
        for token in (
            "restaurant",
            "eat",
            "food",
            "dinner",
            "lunch",
            "breakfast",
            "coffee",
            "bar",
            "drink",
            "seafood",
            "sushi",
            "pizza",
            "burger",
            "recommend",
            "nearby",
            "close to",
            "around here",
            "local",
            "grocery",
            "store",
            "publix",
            "walmart",
            "cvs",
            "pharmacy",
            "hospital",
            "urgent care",
            "doctor",
            "emergency",
            "activity",
            "do",
            "fun",
            "attraction",
            "museum",
            "shopping",
            "event",
            "festival",
            "concert",
        )
    )
