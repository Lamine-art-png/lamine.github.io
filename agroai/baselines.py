from datetime import date

def vine_generic_v1(day: date) -> float:
    """
    Very simple, slightly over-watering baseline:
    fixed 0.20 inches every day of the season.
    """
    return 0.20


def almond_generic_v1(day: date) -> float:
    """
    Very rough almond schedule example.
    """
    year = day.year
    mar_1 = date(year, 3, 1)
    jun_1 = date(year, 6, 1)
    sep_1 = date(year, 9, 1)
    nov_1 = date(year, 11, 1)

    if day < mar_1 or day >= nov_1:
        return 0.0

    # Mar–May: 2x/week, 0.7"
    if mar_1 <= day < jun_1:
        return 0.7 if day.weekday() in (1, 4) else 0.0  # Tue, Fri

    # Jun–Aug: 3x/week, 1.0"
    if jun_1 <= day < sep_1:
        return 1.0 if day.weekday() in (1, 3, 5) else 0.0

    # Sep–Oct: 1x/week, 0.6"
    return 0.6 if day.weekday() == 2 else 0.0


BASELINES = {
    "vine_generic_v1": vine_generic_v1,
    "almond_generic_v1": almond_generic_v1,
}

