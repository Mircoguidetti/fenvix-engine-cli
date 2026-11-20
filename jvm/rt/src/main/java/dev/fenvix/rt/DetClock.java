package dev.fenvix.rt;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;

/** A {@link Clock} that reads the virtual clock (returned by Clock.systemUTC() etc. under --det). */
public final class DetClock extends Clock {
    private final ZoneId zone;
    private final String site;

    public DetClock(ZoneId zone, String site) {
        this.zone = zone;
        this.site = site;
    }

    @Override
    public ZoneId getZone() {
        return zone;
    }

    @Override
    public Clock withZone(ZoneId z) {
        return z.equals(zone) ? this : new DetClock(z, site);
    }

    @Override
    public Instant instant() {
        return Det.TIME ? Det.clockInstant(site) : Instant.now();
    }

    @Override
    public long millis() {
        return Det.TIME ? Det.clockMillis(site) : System.currentTimeMillis();
    }

    @Override
    public boolean equals(Object o) {
        return o instanceof DetClock && ((DetClock) o).zone.equals(zone);
    }

    @Override
    public int hashCode() {
        return zone.hashCode() + 1;
    }

    @Override
    public String toString() {
        return "SystemClock[" + zone + "]";
    }
}
