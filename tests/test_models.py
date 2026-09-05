from src.models import Schedule, Slot, WeatherPoint


def test_slot_defaults_to_no_players():
    slot = Slot(time="09:10", booked=0, capacity=4)
    assert slot.players == []


def test_schedule_holds_slots_and_weather():
    schedule = Schedule(
        date="2026-09-05",
        course="Main",
        slots=[Slot(time="09:10", booked=2, capacity=4, players=["Alice", "Bob"])],
        weather=[WeatherPoint(time="09:10", precipitation_probability=10.0)],
    )
    assert schedule.slots[0].booked == 2
    assert schedule.weather[0].precipitation_probability == 10.0
