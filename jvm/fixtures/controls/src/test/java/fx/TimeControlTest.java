package fx;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZonedDateTime;
import java.util.Calendar;
import java.util.Date;
import org.junit.jupiter.api.Test;

/** Control "time": the wall clock restarts at the same epoch in every test under --det. */
class TimeControlTest {
    @Test
    void currentTimeMillis() throws Exception {
        Same.check("currentTimeMillis", System.currentTimeMillis());
    }

    @Test
    void instantNow() throws Exception {
        Same.check("instantNow", Instant.now());
    }

    @Test
    void localDateTimeNow() throws Exception {
        Same.check("localDateTimeNow", LocalDateTime.now());
    }

    @Test
    void zonedDateTimeNow() throws Exception {
        Same.check("zonedDateTimeNow", ZonedDateTime.now(java.time.ZoneOffset.UTC));
    }

    @Test
    void newDate() throws Exception {
        Same.check("newDate", new Date().getTime());
    }

    @Test
    void clockSystemUtc() throws Exception {
        Same.check("clockSystemUtc", Clock.systemUTC().millis());
    }

    @Test
    void calendar() throws Exception {
        Same.check("calendar", Calendar.getInstance().getTimeInMillis());
    }

    @Test
    void nanoTimeDelta() throws Exception {
        long a = System.nanoTime();
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 1000; i++) sb.append(i);
        Same.check("nanoTimeDelta", System.nanoTime() - a);
    }
}
