package fx;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTimeoutPreemptively;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

/** Control "sched": scheduled executors run on virtual time. */
class SchedControlTest {
    @Test
    void delayedTaskFiresWithoutWaiting() {
        assertTimeoutPreemptively(Duration.ofMillis(1500), () -> {
            ScheduledExecutorService ses = Executors.newSingleThreadScheduledExecutor();
            CountDownLatch done = new CountDownLatch(1);
            ses.schedule(done::countDown, 3, TimeUnit.SECONDS);
            assertTrue(done.await(10, TimeUnit.SECONDS));
            ses.shutdown();
        });
    }

    @Test
    void fixedRateTicksWithoutWaiting() {
        assertTimeoutPreemptively(Duration.ofMillis(1500), () -> {
            ScheduledExecutorService ses = Executors.newScheduledThreadPool(2);
            CountDownLatch five = new CountDownLatch(5);
            ses.scheduleAtFixedRate(five::countDown, 1, 1, TimeUnit.SECONDS);
            assertTrue(five.await(30, TimeUnit.SECONDS));
            ses.shutdownNow();
        });
    }

    @Test
    void timersFireInDueOrder() throws Exception {
        ScheduledExecutorService ses = Executors.newScheduledThreadPool(4);
        List<Integer> order = Collections.synchronizedList(new ArrayList<>());
        CountDownLatch all = new CountDownLatch(3);
        ses.schedule(() -> { order.add(3); all.countDown(); }, 300, TimeUnit.MILLISECONDS);
        ses.schedule(() -> { order.add(1); all.countDown(); }, 100, TimeUnit.MILLISECONDS);
        ses.schedule(() -> { order.add(2); all.countDown(); }, 200, TimeUnit.MILLISECONDS);
        assertTrue(all.await(10, TimeUnit.SECONDS));
        assertEquals(java.util.Arrays.asList(1, 2, 3), order);
        ses.shutdown();
    }

    @Test
    void shorterTimeoutStillExpiresFirst() throws Exception {
        // semantics kept: a 300 ms wait times out before a task due at 2 s
        ScheduledExecutorService ses = Executors.newSingleThreadScheduledExecutor();
        CountDownLatch done = new CountDownLatch(1);
        ses.schedule(done::countDown, 2, TimeUnit.SECONDS);
        assertFalse(done.await(300, TimeUnit.MILLISECONDS));
        ses.shutdownNow();
    }
}
