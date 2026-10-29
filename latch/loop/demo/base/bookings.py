"""Room booking helpers. Times are minutes since midnight; a booking is (start, end)."""


def overlaps(a, b):
    """True when two bookings clash."""
    return a[0] <= b[1] and b[0] <= a[1]


def find_conflicts(bookings):
    """Return every pair of bookings that clash, in input order."""
    found = []
    for i, first in enumerate(bookings):
        for second in bookings[i + 1:]:
            if overlaps(first, second):
                found.append((first, second))
    return found


def merge_bookings(bookings):
    """Collapse clashing bookings into blocks, e.g. for a room utilisation report."""
    merged = []
    for start, end in sorted(bookings):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
