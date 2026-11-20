package dev.fenvix.rt;

import java.lang.reflect.Field;
import java.util.Random;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Reseeds the JDK's own hidden generators at every test boundary: the Random
 * behind Math.random and StrictMath.random, the one behind
 * Collections.shuffle(List), the seed generator of new SplittableRandom() and
 * of ThreadLocalRandom, and the ThreadLocalRandom state of the thread running
 * the test. Needs java.lang, java.util and java.util.concurrent opened to the
 * fenvix runtime (the agent does it with Instrumentation.redefineModule).
 */
final class JdkRandoms {
    private JdkRandoms() {}

    static Field mathHolder, strictHolder, collectionsR, splittableGen, tlrSeeder, threadSeed, threadProbe, threadSecondary;
    static boolean init;

    static synchronized void init() {
        if (init) return;
        init = true;
        try {
            mathHolder = Det.field(Class.forName("java.lang.Math$RandomNumberGeneratorHolder"), "randomNumberGenerator");
        } catch (Throwable ignored) {
            // not present
        }
        try {
            strictHolder = Det.field(Class.forName("java.lang.StrictMath$RandomNumberGeneratorHolder"), "randomNumberGenerator");
        } catch (Throwable ignored) {
            // not present
        }
        collectionsR = Det.field(java.util.Collections.class, "r");
        splittableGen = Det.field(java.util.SplittableRandom.class, "defaultGen");
        tlrSeeder = Det.field(java.util.concurrent.ThreadLocalRandom.class, "seeder");
        threadSeed = Det.field(Thread.class, "threadLocalRandomSeed");
        threadProbe = Det.field(Thread.class, "threadLocalRandomProbe");
        threadSecondary = Det.field(Thread.class, "threadLocalRandomSecondarySeed");
    }

    /** Which hidden generators could be reached (written in the trace header). */
    static String reachable() {
        init();
        StringBuilder sb = new StringBuilder();
        if (mathHolder != null) sb.append("Math.random,");
        if (strictHolder != null) sb.append("StrictMath.random,");
        if (collectionsR != null) sb.append("Collections.shuffle,");
        if (splittableGen != null) sb.append("SplittableRandom,");
        if (tlrSeeder != null) sb.append("ThreadLocalRandom.seeder,");
        if (threadSeed != null && threadProbe != null) sb.append("ThreadLocalRandom.thread,");
        return sb.length() == 0 ? "" : sb.substring(0, sb.length() - 1);
    }

    static void reseed(long s) {
        init();
        try {
            if (mathHolder != null) ((Random) mathHolder.get(null)).setSeed(s ^ 0x1L);
            if (strictHolder != null) ((Random) strictHolder.get(null)).setSeed(s ^ 0x2L);
            if (collectionsR != null) collectionsR.set(null, new Random(s ^ 0x3L));
            if (splittableGen != null) ((AtomicLong) splittableGen.get(null)).set(s ^ 0x4L);
            if (tlrSeeder != null) ((AtomicLong) tlrSeeder.get(null)).set(s ^ 0x5L);
            seedThread(Thread.currentThread(), s ^ 0x6L);
        } catch (Throwable ignored) {
            // best effort: reported through reachable()
        }
    }

    static void seedThread(Thread t, long s) {
        init();
        try {
            if (threadSeed != null && threadProbe != null) {
                threadSeed.setLong(t, s);
                int probe = (int) (s >>> 32) | 1;
                threadProbe.setInt(t, probe);
                if (threadSecondary != null) threadSecondary.setInt(t, (int) s | 1);
            }
        } catch (Throwable ignored) {
            // best effort
        }
    }
}
