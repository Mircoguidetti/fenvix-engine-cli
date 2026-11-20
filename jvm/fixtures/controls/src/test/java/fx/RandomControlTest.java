package fx;

import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;
import java.util.SplittableRandom;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ThreadLocalRandom;
import org.junit.jupiter.api.Test;

/** Control "random": every generator gives the same values in every run under --det. */
class RandomControlTest {
    @Test
    void newRandom() throws Exception {
        Same.check("newRandom", new Random().nextLong());
    }

    @Test
    void mathRandom() throws Exception {
        Same.check("mathRandom", Math.random());
    }

    @Test
    void threadLocalRandom() throws Exception {
        Same.check("threadLocalRandom", ThreadLocalRandom.current().nextLong());
    }

    @Test
    void threadLocalRandomInPool() throws Exception {
        Same.check("threadLocalRandomInPool", CompletableFuture.supplyAsync(() -> ThreadLocalRandom.current().nextInt()).get());
    }

    @Test
    void secureRandom() throws Exception {
        Same.check("secureRandom", new SecureRandom().nextLong());
    }

    @Test
    void secureRandomStrong() throws Exception {
        Same.check("secureRandomSha1prng", SecureRandom.getInstance("SHA1PRNG").nextInt());
    }

    @Test
    void uuid() throws Exception {
        Same.check("uuid", UUID.randomUUID());
    }

    @Test
    void collectionsShuffle() throws Exception {
        List<Integer> l = new ArrayList<>();
        for (int i = 0; i < 20; i++) l.add(i);
        Collections.shuffle(l);
        Same.check("collectionsShuffle", l);
    }

    @Test
    void splittableRandom() throws Exception {
        Same.check("splittableRandom", new SplittableRandom().nextLong());
    }
}
