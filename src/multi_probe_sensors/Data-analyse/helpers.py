from datetime import date, timedelta

from datetime import datetime, timedelta

def daterange(start, stop=None, step=1, fmt="%Y-%m-%d"):
    # accepts strings like "2024-01-01"
    if stop is None:
        start, stop = datetime.today(), datetime.strptime(start, fmt)
    else:
        start = datetime.strptime(start, fmt)
        stop = datetime.strptime(stop, fmt)

    if step == 0:
        raise ValueError("step must not be 0")

    current = start
    delta = timedelta(days=step)

    if step > 0:
        while current < stop:
            yield current.strftime(fmt)
            current += delta
    else:
        while current > stop:
            yield current.strftime(fmt)
            current += delta