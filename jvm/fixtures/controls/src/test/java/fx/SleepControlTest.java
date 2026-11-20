package fx;

import static org.junit.jupiter.api.Assertions.assertTimeoutPreemptively;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

/** Control "time": sleeps advance the virtual clock without waiting when no other thread works. */
class SleepControlTest {
    @Test
    void threadSleepIsVirtual() {
        assertTimeoutPreemptively(Duration.ofMillis(1500), () -> {
            long t0 = System.nanoTime();
            Thread.sleep(3_000);
            assertTrue(System.nanoTime() - t0 >= 3_000_000_000L, "virtual clock advanced by the sleep");
        });
    }

    @Test
    void timeUnitSleepIsVirtual() {
        assertTimeoutPreemptively(Duration.ofMillis(1500), () -> TimeUnit.SECONDS.sleep(3));
    }

    @Test
    void busyWaitOnTheClockEnds() {
        // a deadline loop on the clock ends (adaptive tick) under --det, and in real time without it
        assertTimeoutPreemptively(Duration.ofSeconds(20), () -> {
            long end = System.currentTimeMillis() + 2_000;
            long n = 0;
            while (System.currentTimeMillis() < end) n++;
            assertTrue(n > 0);
        });
    }
}
