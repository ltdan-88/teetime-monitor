from src.playability import is_playable, latest_playable_start


def test_latest_playable_start_subtracts_duration_and_buffer():
    # Sunset 19:47, 4h round, 30 min buffer -> 15:17
    assert latest_playable_start("19:47", duration_minutes=240, buffer_minutes=30) == "15:17"


def test_latest_playable_start_with_no_buffer():
    assert latest_playable_start("19:47", duration_minutes=240) == "15:47"


def test_slot_before_cutoff_is_playable():
    assert is_playable("14:00", sunset="19:47", duration_minutes=240, buffer_minutes=30)


def test_slot_after_cutoff_is_not_playable():
    assert not is_playable("16:00", sunset="19:47", duration_minutes=240, buffer_minutes=30)


def test_nine_hole_round_is_playable_later_than_eighteen():
    sunset = "19:47"
    nine_ok = is_playable("17:00", sunset=sunset, duration_minutes=120, buffer_minutes=30)
    eighteen_ok = is_playable("17:00", sunset=sunset, duration_minutes=240, buffer_minutes=30)
    assert nine_ok and not eighteen_ok
