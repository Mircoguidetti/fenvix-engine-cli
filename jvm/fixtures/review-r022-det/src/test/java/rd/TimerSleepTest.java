package rd;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

/**
 * The shape of luwak TestCachePurging.testBackgroundPurges: a background task at a fixed rate of 1 s,
 * the test sleeps 2 s and expects the task to have run. Passes without --det (real time).
 */
class TimerSleepTest {
    @Test
    void sleepPastFixedRateTimer() throws Exception {
        ScheduledExecutorService ex = Executors.newSingleThreadScheduledExecutor();
        AtomicInteger runs = new AtomicInteger();
        try {
            ex.scheduleAtFixedRate(runs::incrementAndGet, 1, 1, TimeUnit.SECONDS);
            TimeUnit.SECONDS.sleep(2);
            assertTrue(runs.get() >= 1, "fixed-rate task ran " + runs.get() + " times in a 2 s sleep");
        } finally {
            ex.shutdownNow();
        }
    }
}
