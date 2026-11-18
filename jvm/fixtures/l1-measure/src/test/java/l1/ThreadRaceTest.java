package l1;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

/** Level 1 (thread interleaving), measured only: Level 0 does not order threads. */
class ThreadRaceTest {
    static int counter;

    @Test
    void unsynchronizedCounter() throws Exception {
        counter = 0;
        Thread[] ts = new Thread[4];
        for (int i = 0; i < ts.length; i++) {
            ts[i] = new Thread(() -> {
                for (int k = 0; k < 50_000; k++) counter++;
            });
            ts[i].start();
        }
        for (Thread t : ts) t.join();
        assertEquals(200_000, counter);
    }

    @Test
    void completionOrder() throws Exception {
        ExecutorService ex = Executors.newFixedThreadPool(4);
        List<Integer> done = Collections.synchronizedList(new ArrayList<>());
        for (int i = 0; i < 8; i++) {
            int id = i;
            ex.submit(() -> {
                long x = 0;
                for (int k = 0; k < 200_000 * (8 - id); k++) x += k;
                if (x == 42) System.out.print("");
                done.add(id);
            });
        }
        ex.shutdown();
        ex.awaitTermination(30, TimeUnit.SECONDS);
        assertEquals(List.of(0, 1, 2, 3, 4, 5, 6, 7), done);
    }
}
