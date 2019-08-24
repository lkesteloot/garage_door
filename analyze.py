
# Generates statistics from the garage door database.

import sqlite3
import datetime
import collections

def main():
    db = sqlite3.connect("/var/opt/garage/mctool.db")

    c = db.cursor()
    c.execute("""SELECT message, created_at
                 FROM event
                 ORDER BY id""")
    events = list(c)
    c.close()

    lastOpen = None
    counts = collections.Counter()
    hours = collections.Counter()
    for message, createdAt in events:
        # 2013-03-24 16:24:46
        createdAt = datetime.datetime.strptime(createdAt, "%Y-%m-%d %H:%M:%S")
        # print message, createdAt
        if message == "Door is now open":
            lastOpen = createdAt
            # UTC to Pacific.
            hour = (createdAt.hour - 7 + 24) % 24
            hours[hour] += 1
        elif message == "Door is now closed":
            if lastOpen is not None:
                wasOpenFor = createdAt - lastOpen
                # print wasOpenFor
                minutes = wasOpenFor.seconds // 60
                counts[minutes] += 1
            lastOpen = None

    print "Minutes   Count"
    for minutes in range(max(counts.keys()) + 1):
        c = counts[minutes]
        print "%7d %7d  %s" % (minutes, c, "*"*c)
    print
    print "Hour Count"
    for hour in range(24):
        c = hours[hour]
        print "%4d %5d  %s" % (hour, c, "*"*c)

main()
