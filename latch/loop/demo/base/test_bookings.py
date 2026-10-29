from bookings import find_conflicts, merge_bookings, overlaps


def test_overlapping_bookings_clash():
    assert overlaps((540, 600), (570, 630))


def test_disjoint_bookings_do_not_clash():
    assert not overlaps((540, 600), (700, 760))


def test_find_conflicts_reports_clashing_pair():
    bookings = [(540, 600), (570, 630), (800, 860)]
    assert find_conflicts(bookings) == [((540, 600), (570, 630))]


def test_merge_joins_overlapping_bookings():
    assert merge_bookings([(540, 600), (570, 630), (800, 860)]) == [(540, 630), (800, 860)]
