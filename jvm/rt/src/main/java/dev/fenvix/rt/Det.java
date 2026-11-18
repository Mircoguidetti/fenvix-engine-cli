package dev.fenvix.rt;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.net.ConnectException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.OpenOption;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Calendar;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.Random;
import java.util.Set;
import java.util.TimeZone;
import java.util.UUID;
import java.util.WeakHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.LockSupport;

/**
 * The Level 0 runtime of the JVM shell. Rewritten call sites in code under test
 * (see the agent's CallSiteRewriter) and hooks in a few JDK methods call the
 * static methods of this class. Every method is safe to call when the controls
 * are off: it then behaves like the original.
 *
 * <p>Controls ({@code fenvix.disable} switches them off one by one): {@code order}
 * (JUnit orderers, not here), {@code random}, {@code time}, {@code fs},
 * {@code net}, {@code sched} (scheduled executors).
 */
public final class Det {
    private Det() {}

    // ------------------------------------------------------------------ config
    /** Level 0 controls active (--det). */
    public static volatile boolean ON;
    /** Skip-with-proof capture active. */
    public static volatile boolean DEPS;
    public static boolean RANDOM, TIME, FS, NET, SCHED;
    public static long SEED;
    static long TICK_NS = 1_000;
    static int ADAPT_AFTER = 1_000;
    static long EPOCH_MS = 1_735_689_600_000L; // 2025-01-01T00:00:00Z
    static final long MONO_BASE_NS = 1_000_000_000_000L;
    static final long MAX_TICK_NS = 1_000_000_000L;
    static int TIMER_BUDGET = 100_000;
    static Set<String> ALLOW_HOSTS = new HashSet<>();
    static String ROOT = "";
    static String MODULE = "";
    static String OUT = "";

    /** Called once by the agent after the native library is loaded. */
    public static void configure() {
        ON = bool("fenvix.det");
        DEPS = bool("fenvix.deps");
        String dis = "," + System.getProperty("fenvix.disable", "") + ",";
        RANDOM = ON && !dis.contains(",random,");
        TIME = ON && !dis.contains(",time,");
        FS = ON && !dis.contains(",fs,");
        NET = ON && !dis.contains(",net,");
        SCHED = TIME && !dis.contains(",sched,");
        SEED = Long.parseLong(System.getProperty("fenvix.seed", "0"));
        TICK_NS = Long.parseLong(System.getProperty("fenvix.tick.ns", "1000"));
        ADAPT_AFTER = Integer.parseInt(System.getProperty("fenvix.adapt", "1000"));
        EPOCH_MS = Long.parseLong(System.getProperty("fenvix.epoch.ms", String.valueOf(EPOCH_MS)));
        TIMER_BUDGET = Integer.parseInt(System.getProperty("fenvix.timer.budget", "100000"));
        for (String h : System.getProperty("fenvix.allow.hosts", "").split(",")) {
            if (!h.trim().isEmpty()) ALLOW_HOSTS.add(h.trim().toLowerCase(Locale.ROOT));
        }
        ROOT = System.getProperty("fenvix.root", System.getProperty("user.dir"));
        MODULE = System.getProperty("fenvix.module", "");
        OUT = System.getProperty("fenvix.out", ROOT + "/.fenvix");
        CLOCK_TICK = TICK_NS;
        seedSession();
    }

    static boolean bool(String k) {
        String v = System.getProperty(k, "");
        return v.equals("1") || v.equalsIgnoreCase("true") || v.equalsIgnoreCase("yes");
    }

    public static String controls() {
        List<String> c = new ArrayList<>();
        if (ON) c.add("order");
        if (RANDOM) c.add("random");
        if (TIME) c.add("time");
        if (FS) c.add("fs");
        if (NET) c.add("net");
        if (SCHED) c.add("sched");
        return String.join(",", c);
    }

    // ------------------------------------------------------------- test state
    static volatile String TEST; // current test id (null outside tests)
    static volatile int TEST_EPOCH;
    static volatile Thread TEST_THREAD;
    static long RECORDER;
    static final StringBuilder BUF = new StringBuilder();
    static final Object LOCK = new Object();
    static int nextThreadNo;
    static final ThreadLocal<int[]> THREAD_NO = ThreadLocal.withInitial(() -> new int[] {-1, 0});
    static final ThreadLocal<int[]> IN_HOOK = ThreadLocal.withInitial(() -> new int[1]);

    public static boolean inTest() {
        return TEST != null;
    }

    public static String currentTest() {
        return TEST;
    }

    /** Open the trace part of this JVM. */
    public static void openTrace(String path, String metaJson, String[] order) {
        if (!Native.isLoaded()) return;
        synchronized (LOCK) {
            if (RECORDER == 0) RECORDER = Native.recorderNew(10_000, 256);
            Native.recorderOpen(RECORDER, path, metaJson, order);
        }
    }

    public static String closeTrace() {
        synchronized (LOCK) {
            if (RECORDER == 0) return null;
            flush();
            String d = Native.recorderClose(RECORDER);
            return d;
        }
    }

    /** Start of a test: reseed, reset the wall clock, start the fingerprint. */
    public static void beginTest(String id, int index) {
        synchronized (LOCK) {
            TEST = id;
            TEST_EPOCH++;
            TEST_THREAD = Thread.currentThread();
            nextThreadNo = 1;
            THREAD_NO.get()[0] = TEST_EPOCH;
            THREAD_NO.get()[1] = 0;
            fastFirings = 0;
            snapshotBaseline();
            if (RECORDER != 0) Native.recorderBegin(RECORDER, id, index);
        }
        clockStartTest();
        reseed(id);
        if (DEPS) Deps.beginTest(id);
    }

    /** End of a test; returns its fingerprint (null without a recorder). */
    public static String endTest(String outcome) {
        String fp = null;
        if (DEPS) Deps.endTest(outcome);
        synchronized (LOCK) {
            if (RECORDER != 0 && TEST != null) {
                flush();
                fp = Native.recorderEnd(RECORDER, outcome);
            }
            TEST = null;
            TEST_THREAD = null;
        }
        reseed("<between>");
        return fp;
    }

    static int threadNo() {
        int[] t = THREAD_NO.get();
        if (t[0] != TEST_EPOCH) {
            synchronized (LOCK) {
                t[0] = TEST_EPOCH;
                t[1] = nextThreadNo++;
            }
        }
        return t[1];
    }

    /** Record one event of the current test (dropped outside tests). */
    /** Test epoch in which a thread was first seen (0 = outside any test). */
    static final ThreadLocal<int[]> BIRTH = ThreadLocal.withInitial(() -> new int[] {-1});
    /** Events of threads left over from earlier tests, not part of the current fingerprint. */
    public static volatile long LEAKED_EVENTS;

    public static void record(String source, String op, String site, String value) {
        int[] birth = BIRTH.get();
        if (birth[0] < 0) birth[0] = TEST == null ? 0 : TEST_EPOCH;
        if (TEST == null || RECORDER == 0) return;
        if (birth[0] != TEST_EPOCH && Thread.currentThread() != TEST_THREAD) {
            // a thread born before this test (leaked by an earlier test, or a shared pool
            // created outside tests): its activity is timed by other tests, not by this one
            LEAKED_EVENTS++;
            return;
        }
        int th = threadNo();
        if (!"time".equals(source)) clockOtherEvent();
        int[] f = IN_HOOK.get();
        int prev = f[0];
        f[0] = 1; // resolving the site may list directories: no nested events
        String at;
        try {
            at = Sites.resolve(site);
        } finally {
            f[0] = prev;
        }
        synchronized (LOCK) {
            if (TEST == null) return;
            BUF.append(th).append('\u001f').append(source).append('\u001f').append(op).append('\u001f')
                    .append(at).append('\u001f').append(value).append('\u001e');
            if (BUF.length() > 1 << 16) flush();
        }
    }

    static void flush() {
        if (BUF.length() == 0 || RECORDER == 0) return;
        Native.recorderRecordPacked(RECORDER, BUF.toString());
        BUF.setLength(0);
    }

    // ---------------------------------------------------------- virtual clock
    static final Object CLK = new Object();
    static long elapsed;
    static long CLOCK_TICK = 1_000;
    static int streak;
    static long testStart;
    static long wallOffsetNs = EPOCH_MS * 1_000_000L;

    static final java.util.concurrent.atomic.AtomicInteger REAL_SLEEPERS = new java.util.concurrent.atomic.AtomicInteger();
    /** Threads inside a real sleep slice of Det.sleep. */
    static final java.util.concurrent.ConcurrentHashMap<Thread, Boolean> REAL_SLEEPING = new java.util.concurrent.ConcurrentHashMap<>();

    /** A clock-polling loop runs while another thread works: its clock follows real time. */
    static boolean pollingOthers;
    static long lastRealRead;

    static long clockRead() {
        boolean check = false;
        synchronized (CLK) {
            if (ADAPT_AFTER > 0 && streak >= ADAPT_AFTER && (streak - ADAPT_AFTER) % 1024 == 0) check = true;
        }
        // outside the clock lock: looks at the other threads (every 1024 reads of a streak)
        boolean others = check ? !quiet(Thread.currentThread()) : false;
        synchronized (CLK) {
            if (check) {
                pollingOthers = others;
                lastRealRead = System.nanoTime();
            }
            if (pollingOthers && streak >= ADAPT_AFTER) {
                // waiting for another thread by polling the clock (a busy deadline loop): advance by
                // the real time spent, never faster, so the deadline means what it means in real time
                long now = System.nanoTime();
                long real = now - lastRealRead;
                lastRealRead = now;
                CLOCK_TICK = TICK_NS;
                elapsed += Math.max(TICK_NS, real);
                ++streak;
                return elapsed;
            }
            elapsed += CLOCK_TICK;
            // no acceleration while a thread sleeps for real: it lets another thread work in
            // real time, and that thread's clock polling must not race ahead of it
            if (ADAPT_AFTER > 0 && ++streak > ADAPT_AFTER && REAL_SLEEPERS.get() == 0) {
                CLOCK_TICK = Math.min(Math.max(1, CLOCK_TICK) * 2, MAX_TICK_NS);
            }
            return elapsed;
        }
    }

    static long clockPeek() {
        synchronized (CLK) {
            return elapsed;
        }
    }

    static void clockOtherEvent() {
        if (streak == 0 && CLOCK_TICK == TICK_NS && !pollingOthers) return;
        synchronized (CLK) {
            pollingOthers = false;
            streak = 0;
            CLOCK_TICK = TICK_NS;
        }
    }

    /** Advance the virtual clock by {@code ns} (sleeps, timed waits). */
    public static void advance(long ns) {
        if (ns <= 0) return;
        synchronized (CLK) {
            elapsed += ns;
            streak = 0;
            CLOCK_TICK = TICK_NS;
        }
    }

    /**
     * A wait that started at virtual time {@code start} (elapsed ns) and lasted {@code ns}:
     * the clock moves to start + ns if it is behind. Concurrent waits overlap instead of
     * adding up (two threads sleeping 100 ms at once move the clock by 100 ms, not 200).
     */
    static void advanceFrom(long start, long ns) {
        if (ns <= 0) return;
        synchronized (CLK) {
            if (start + ns > elapsed) elapsed = start + ns;
            streak = 0;
            CLOCK_TICK = TICK_NS;
        }
    }

    /** Move the virtual monotonic clock forward to {@code monoNs} if behind. */
    static void advanceTo(long monoNs) {
        synchronized (CLK) {
            long e = monoNs - MONO_BASE_NS;
            if (e > elapsed) elapsed = e;
        }
    }

    /** virtual wall ms - real wall ms, taken at each test start (file timestamps). */
    static volatile long FILE_TIME_OFFSET_MS;

    /** A real file timestamp (ms) as seen on the virtual clock, for code under test. */
    public static long mtimeFromReal(long realMs) {
        if (!TIME || realMs == 0) return realMs;
        if (!enter()) return realMs;
        try {
            return Caller.user() != null ? realMs + FILE_TIME_OFFSET_MS : realMs;
        } finally {
            exit();
        }
    }

    /** A virtual timestamp written by code under test (File.setLastModified) back to real time. */
    public static long mtimeToReal(long virtualMs) {
        if (!TIME || virtualMs <= 0) return virtualMs;
        if (!enter()) return virtualMs;
        try {
            return Caller.user() != null ? Math.max(1, virtualMs - FILE_TIME_OFFSET_MS) : virtualMs;
        } finally {
            exit();
        }
    }

    public static java.nio.file.attribute.FileTime fileTimeFromReal(java.nio.file.attribute.FileTime t) {
        if (!TIME || t == null) return t;
        long ms = t.toMillis();
        long v = mtimeFromReal(ms);
        return v == ms ? t : java.nio.file.attribute.FileTime.fromMillis(v);
    }

    static void clockStartTest() {
        synchronized (CLK) {
            streak = 0;
            pollingOthers = false;
            CLOCK_TICK = TICK_NS;
            testStart = elapsed;
            wallOffsetNs = EPOCH_MS * 1_000_000L - elapsed;
        }
        FILE_TIME_OFFSET_MS = EPOCH_MS - System.currentTimeMillis();
    }

    static String rel(long e) {
        return Long.toString(e - testStart);
    }

    static long wallMillis(String op, String site) {
        long e = clockRead();
        record("time", op, site, rel(e));
        return Math.floorDiv(wallOffsetNs + e, 1_000_000L);
    }

    public static long currentTimeMillis(String site) {
        if (!TIME) return System.currentTimeMillis();
        return wallMillis("System.currentTimeMillis", site);
    }

    public static long nanoTime(String site) {
        if (!TIME) return System.nanoTime();
        long e = clockRead();
        record("time", "System.nanoTime", site, rel(e));
        return MONO_BASE_NS + e;
    }

    /** Virtual monotonic now without ticking (scheduler). */
    static long monoNow() {
        return MONO_BASE_NS + clockPeek();
    }

    public static Instant instantNow(String site) {
        if (!TIME) return Instant.now();
        long e = clockRead();
        record("time", "Instant.now", site, rel(e));
        long w = wallOffsetNs + e;
        return Instant.ofEpochSecond(Math.floorDiv(w, 1_000_000_000L), Math.floorMod(w, 1_000_000_000L));
    }

    /** Instant read through a {@link DetClock}. */
    static Instant clockInstant(String site) {
        long e = clockRead();
        record("time", "Clock.instant", site, rel(e));
        long w = wallOffsetNs + e;
        return Instant.ofEpochSecond(Math.floorDiv(w, 1_000_000_000L), Math.floorMod(w, 1_000_000_000L));
    }

    static long clockMillis(String site) {
        return wallMillis("Clock.millis", site);
    }

    public static Clock clockUTC(String site) {
        if (!TIME) return Clock.systemUTC();
        return new DetClock(java.time.ZoneOffset.UTC, site);
    }

    public static Clock clockDefaultZone(String site) {
        if (!TIME) return Clock.systemDefaultZone();
        return new DetClock(ZoneId.systemDefault(), site);
    }

    public static Clock clockSystem(ZoneId zone, String site) {
        if (!TIME) return Clock.system(zone);
        return new DetClock(zone, site);
    }

    public static Calendar calendarGetInstance(String site) {
        Calendar c = Calendar.getInstance();
        if (TIME) c.setTimeInMillis(wallMillis("Calendar.getInstance", site));
        return c;
    }

    public static Calendar calendarGetInstanceTz(TimeZone tz, String site) {
        Calendar c = Calendar.getInstance(tz);
        if (TIME) c.setTimeInMillis(wallMillis("Calendar.getInstance", site));
        return c;
    }

    public static Calendar calendarGetInstanceLocale(Locale l, String site) {
        Calendar c = Calendar.getInstance(l);
        if (TIME) c.setTimeInMillis(wallMillis("Calendar.getInstance", site));
        return c;
    }

    public static Calendar calendarGetInstanceTzLocale(TimeZone tz, Locale l, String site) {
        Calendar c = Calendar.getInstance(tz, l);
        if (TIME) c.setTimeInMillis(wallMillis("Calendar.getInstance", site));
        return c;
    }

    // --------------------------------------------------------- sleeps, waits
    /**
     * Thread.sleep: the virtual clock advances by the requested time; the thread
     * also sleeps for real while another thread of the test may be working (the
     * Python rule "sleep for real while other threads are alive").
     */
    public static void sleep(long ms, String site) throws InterruptedException {
        if (!TIME) {
            Thread.sleep(ms);
            return;
        }
        if (ms < 0) throw new IllegalArgumentException("timeout value is negative");
        record("time", "Thread.sleep", site, Long.toString(ms));
        long vstart = clockPeek();
        // sleep for real only while another thread may be working, re-checking every 10 ms
        long left = ms;
        Thread self = Thread.currentThread();
        while (left > 0 && !quiet(self)) {
            long slice = Math.min(left, 10);
            REAL_SLEEPERS.incrementAndGet();
            REAL_SLEEPING.put(self, Boolean.TRUE);
            try {
                Thread.sleep(slice);
            } finally {
                REAL_SLEEPING.remove(self);
                REAL_SLEEPERS.decrementAndGet();
            }
            left -= slice;
        }
        if (Thread.interrupted()) throw new InterruptedException("sleep interrupted");
        advanceFrom(vstart, ms * 1_000_000L);
    }

    public static void sleep2(long ms, int nanos, String site) throws InterruptedException {
        if (!TIME) {
            Thread.sleep(ms, nanos);
            return;
        }
        sleep(ms + (nanos >= 500_000 ? 1 : 0), site);
    }

    public static void sleepDuration(Duration d, String site) throws InterruptedException {
        sleep(Math.max(0, d.toMillis()), site);
    }

    public static void timeUnitSleep(TimeUnit u, long t, String site) throws InterruptedException {
        if (!TIME) {
            u.sleep(t);
            return;
        }
        if (t > 0) sleep(u.toMillis(t), site);
    }

    /** Object.wait(ms): real wait; a wait that timed out advances the virtual clock. */
    public static void objectWait(Object o, long ms, String site) throws InterruptedException {
        if (!TIME || ms <= 0) {
            o.wait(ms);
            return;
        }
        long t0 = System.nanoTime();
        long vstart = clockPeek();
        waiting(ms * 1_000_000L);
        try {
            o.wait(ms);
        } finally {
            done();
        }
        timedOut(t0, vstart, ms * 1_000_000L, "Object.wait", site);
    }

    static void timedOut(long t0, long vstart, long ns, String op, String site) {
        long el = System.nanoTime() - t0;
        if (el >= ns - ns / 10) {
            record("time", op, site, "timeout:" + ns);
            advanceFrom(vstart, ns);
        }
    }

    public static void parkNanos(long ns, String site) {
        if (!TIME || ns <= 0) {
            LockSupport.parkNanos(ns);
            return;
        }
        long t0 = System.nanoTime();
        long vstart = clockPeek();
        waiting(ns);
        try {
            LockSupport.parkNanos(ns);
        } finally {
            done();
        }
        timedOut(t0, vstart, ns, "LockSupport.parkNanos", site);
    }

    public static void parkNanosBlocker(Object blocker, long ns, String site) {
        if (!TIME || ns <= 0) {
            LockSupport.parkNanos(blocker, ns);
            return;
        }
        long t0 = System.nanoTime();
        long vstart = clockPeek();
        waiting(ns);
        try {
            LockSupport.parkNanos(blocker, ns);
        } finally {
            done();
        }
        timedOut(t0, vstart, ns, "LockSupport.parkNanos", site);
    }

    // untimed waits: tracked so that a released waiter counts as about to run
    public static void latchAwaitUntimed(CountDownLatch l, String site) throws InterruptedException {
        if (!TIME) {
            l.await();
            return;
        }
        waitingOn(Long.MAX_VALUE / 4, l);
        try {
            l.await();
        } finally {
            done();
        }
    }

    public static Object futureGetUntimed(java.util.concurrent.Future<?> f, String site)
            throws InterruptedException, java.util.concurrent.ExecutionException {
        if (!TIME) return f.get();
        waitingOn(Long.MAX_VALUE / 4, f);
        try {
            return f.get();
        } finally {
            done();
        }
    }

    public static Object queueTake(java.util.concurrent.BlockingQueue<?> q, String site) throws InterruptedException {
        if (!TIME) return q.take();
        waitingOn(Long.MAX_VALUE / 4, q);
        try {
            return q.take();
        } finally {
            done();
        }
    }

    public static void threadJoinUntimed(Thread th, String site) throws InterruptedException {
        if (!TIME) {
            th.join();
            return;
        }
        waitingOn(Long.MAX_VALUE / 4, th);
        try {
            th.join();
        } finally {
            done();
        }
    }

    public static boolean latchAwait(CountDownLatch l, long t, TimeUnit u, String site) throws InterruptedException {
        if (!TIME) return l.await(t, u);
        boolean ok;
        long vstart = clockPeek();
        waitingOn(u.toNanos(t), l);
        try {
            ok = l.await(t, u);
        } finally {
            done();
        }
        if (!ok) {
            record("time", "CountDownLatch.await", site, "timeout:" + u.toNanos(t));
            advanceFrom(vstart, u.toNanos(t));
        }
        return ok;
    }

    public static boolean conditionAwait(Condition c, long t, TimeUnit u, String site) throws InterruptedException {
        if (!TIME) return c.await(t, u);
        boolean ok;
        long vstart = clockPeek();
        waiting(u.toNanos(t));
        try {
            ok = c.await(t, u);
        } finally {
            done();
        }
        if (!ok) {
            record("time", "Condition.await", site, "timeout:" + u.toNanos(t));
            advanceFrom(vstart, u.toNanos(t));
        }
        return ok;
    }

    public static long conditionAwaitNanos(Condition c, long ns, String site) throws InterruptedException {
        if (!TIME) return c.awaitNanos(ns);
        long left;
        long vstart = clockPeek();
        waiting(ns);
        try {
            left = c.awaitNanos(ns);
        } finally {
            done();
        }
        if (left <= 0 && ns > 0) {
            record("time", "Condition.awaitNanos", site, "timeout:" + ns);
            advanceFrom(vstart, ns);
        }
        return left;
    }

    public static Object futureGet(java.util.concurrent.Future<?> f, long t, TimeUnit u, String site)
            throws InterruptedException, java.util.concurrent.ExecutionException, java.util.concurrent.TimeoutException {
        if (!TIME) return f.get(t, u);
        long vstart = clockPeek();
        waitingOn(u.toNanos(t), f);
        try {
            return f.get(t, u);
        } catch (java.util.concurrent.TimeoutException e) {
            record("time", "Future.get", site, "timeout:" + u.toNanos(t));
            advanceFrom(vstart, u.toNanos(t));
            throw e;
        } finally {
            done();
        }
    }

    public static Object queuePoll(java.util.concurrent.BlockingQueue<?> q, long t, TimeUnit u, String site) throws InterruptedException {
        if (!TIME) return q.poll(t, u);
        Object o;
        long vstart = clockPeek();
        waitingOn(u.toNanos(t), q);
        try {
            o = q.poll(t, u);
        } finally {
            done();
        }
        if (o == null && t > 0) {
            record("time", "BlockingQueue.poll", site, "timeout:" + u.toNanos(t));
            advanceFrom(vstart, u.toNanos(t));
        }
        return o;
    }

    public static boolean awaitTermination(java.util.concurrent.ExecutorService e, long t, TimeUnit u, String site) throws InterruptedException {
        if (!TIME) return e.awaitTermination(t, u);
        boolean ok;
        long vstart = clockPeek();
        waitingOn(u.toNanos(t), e);
        try {
            ok = e.awaitTermination(t, u);
        } finally {
            done();
        }
        if (!ok && t > 0) {
            record("time", "ExecutorService.awaitTermination", site, "timeout:" + u.toNanos(t));
            advanceFrom(vstart, u.toNanos(t));
        }
        return ok;
    }

    public static void threadJoin(Thread th, long ms, String site) throws InterruptedException {
        if (!TIME || ms <= 0) {
            th.join(ms);
            return;
        }
        long vstart = clockPeek();
        waitingOn(ms * 1_000_000L, th);
        try {
            th.join(ms);
        } finally {
            done();
        }
        if (th.isAlive()) {
            record("time", "Thread.join", site, "timeout:" + ms);
            advanceFrom(vstart, ms * 1_000_000L);
        }
    }

    // ---------------------------------------------- quiescence (other threads)
    static final Set<Thread> BASELINE = Collections.newSetFromMap(new WeakHashMap<>());
    static boolean baselineTaken;

    static void snapshotBaseline() {
        synchronized (BASELINE) {
            if (!baselineTaken) {
                for (Thread t : allThreads()) BASELINE.add(t);
                baselineTaken = true;
            }
            BASELINE.remove(Thread.currentThread());
        }
    }

    static Thread[] allThreads() {
        ThreadGroup g = Thread.currentThread().getThreadGroup();
        while (g.getParent() != null) g = g.getParent();
        Thread[] a = new Thread[g.activeCount() * 2 + 16];
        int n = g.enumerate(a, true);
        return Arrays.copyOf(a, n);
    }

    /** Thread names of infrastructure threads created after the baseline. */
    static boolean infraThread(Thread t) {
        ThreadGroup g = t.getThreadGroup();
        if (g != null && "system".equals(g.getName())) return true; // Reference Handler, Finalizer, ...
        String n = t.getName();
        return n.startsWith("junit-") || n.startsWith("fenvix-") || n.equals("process reaper")
                || n.startsWith("surefire-") || n.startsWith("Common-Cleaner") || n.startsWith("Attach Listener")
                || n.startsWith("Notification Thread") || n.startsWith("Signal Dispatcher");
    }

    /**
     * True when no thread other than {@code self} (and the infrastructure) may be
     * working: every such thread is waiting without a timeout (idle pool threads),
     * or not alive.
     */
    public static boolean quiet(Thread self) {
        for (Thread t : allThreads()) {
            if (t == self || !t.isAlive()) continue;
            synchronized (BASELINE) {
                if (BASELINE.contains(t)) continue;
            }
            if (infraThread(t) || VirtualScheduler.isDispatcher(t)) continue;
            Thread.State s = t.getState();
            if (DEBUG) System.err.println("fenvix-quiet " + self.getName() + " sees " + t.getName() + " " + s + " " + java.util.Arrays.toString(t.getStackTrace()));
            if (s == Thread.State.WAITING || s == Thread.State.TERMINATED || s == Thread.State.NEW) continue;
            if (REAL_SLEEPING.containsKey(t)) return false; // emulating real time: another thread may depend on it
            if (WAITERS.containsKey(t) && released(t)) return false; // released, not yet running
            if (s == Thread.State.TIMED_WAITING && (WAITERS.containsKey(t) || waitingInInfra(t))) continue;
            return false;
        }
        return true;
    }

    static int fastFirings;
    static final boolean DEBUG = Boolean.getBoolean("fenvix.debug.quiet");

    /**
     * A thread in a timed wait whose innermost non-JDK frame is test
     * infrastructure (JUnit waiting for a preemptive-timeout thread, the runner's
     * own polling), or that has no non-JDK frame at all (an idle JDK pool
     * thread): it is waiting, not working.
     */
    static boolean waitingInInfra(Thread t) {
        StackTraceElement[] st = t.getStackTrace();
        for (StackTraceElement e : st) {
            String c = e.getClassName();
            if (c.startsWith("java.") || c.startsWith("jdk.") || c.startsWith("sun.") || c.startsWith("dev.fenvix.")) continue;
            return Infra.isInfraDotted(c);
        }
        // only JDK frames: an idle JDK pool thread (ForkJoinPool.awaitWork, a pool worker's keep-alive poll)
        return true;
    }

    /** Threads inside a rewritten timed wait (waiting for another thread, not working). */
    static final java.util.concurrent.ConcurrentHashMap<Thread, Long> WAITERS = new java.util.concurrent.ConcurrentHashMap<>();
    /** What a waiter waits on, when known: a satisfied target means the waiter is about to run. */
    static final java.util.concurrent.ConcurrentHashMap<Thread, Object> WAIT_TARGET = new java.util.concurrent.ConcurrentHashMap<>();

    /** Enter a timed wait with no known timeout (treated as idle, no deadline). */
    static void waiting() {
        WAITERS.put(Thread.currentThread(), Long.MAX_VALUE);
    }

    /** Enter a timed wait that times out at virtual now + ns. */
    static void waiting(long ns) {
        WAITERS.put(Thread.currentThread(), ns <= 0 ? monoNow() : monoNow() + ns);
    }

    static void waitingOn(long ns, Object target) {
        if (target != null) WAIT_TARGET.put(Thread.currentThread(), target);
        waiting(ns);
    }

    /** The waiter's condition already holds: it has been released and will run. */
    static boolean released(Thread t) {
        Object o = WAIT_TARGET.get(t);
        if (o == null) return false;
        if (o instanceof CountDownLatch) return ((CountDownLatch) o).getCount() == 0;
        if (o instanceof java.util.concurrent.Future) return ((java.util.concurrent.Future<?>) o).isDone();
        if (o instanceof java.util.concurrent.BlockingQueue) return !((java.util.concurrent.BlockingQueue<?>) o).isEmpty();
        if (o instanceof java.util.concurrent.ExecutorService) return ((java.util.concurrent.ExecutorService) o).isTerminated();
        if (o instanceof Thread) return !((Thread) o).isAlive();
        return false;
    }

    /**
     * Quiet, and no thread in a timed wait would time out before {@code due}
     * (virtual monotonic ns): a timer due later than a pending timeout must not
     * fire before that timeout expires.
     */
    static boolean quietUntil(Thread self, long due) {
        if (!quiet(self)) return false;
        for (Long d : WAITERS.values()) if (d < due) return false;
        return true;
    }

    static void done() {
        WAITERS.remove(Thread.currentThread());
        WAIT_TARGET.remove(Thread.currentThread());
    }

    /** One more fast (virtual) timer firing; false once the per-test budget is spent. */
    static boolean takeFastFiring() {
        synchronized (LOCK) {
            return ++fastFirings <= TIMER_BUDGET;
        }
    }

    // -------------------------------------------------------- scheduled pools
    public static ScheduledExecutorService newScheduledThreadPool(int n, String site) {
        if (!SCHED) return java.util.concurrent.Executors.newScheduledThreadPool(n);
        return new VirtualScheduler(Math.max(1, n), null, site);
    }

    public static ScheduledExecutorService newScheduledThreadPoolTf(int n, ThreadFactory tf, String site) {
        if (!SCHED) return java.util.concurrent.Executors.newScheduledThreadPool(n, tf);
        return new VirtualScheduler(Math.max(1, n), tf, site);
    }

    public static ScheduledExecutorService newSingleThreadScheduledExecutor(String site) {
        if (!SCHED) return java.util.concurrent.Executors.newSingleThreadScheduledExecutor();
        return new VirtualScheduler(1, null, site);
    }

    public static ScheduledExecutorService newSingleThreadScheduledExecutorTf(ThreadFactory tf, String site) {
        if (!SCHED) return java.util.concurrent.Executors.newSingleThreadScheduledExecutor(tf);
        return new VirtualScheduler(1, tf, site);
    }

    // ------------------------------------------------------------ randomness
    static final Object RNG = new Object();
    static long randomState; // SplitMix64 state for new Random() seeds and Math.random
    static long secureState; // SecureRandom / UUID stream
    static long tlrBase;
    static int tlrEpoch;

    static long splitmix(long[] st) {
        long z = (st[0] += 0x9E3779B97F4A7C15L);
        z = (z ^ (z >>> 30)) * 0xBF58476D1CE4E5B9L;
        z = (z ^ (z >>> 27)) * 0x94D049BB133111EBL;
        return z ^ (z >>> 31);
    }

    static long nextRandomState() {
        synchronized (RNG) {
            long[] st = {randomState};
            long v = splitmix(st);
            randomState = st[0];
            return v;
        }
    }

    static long nextSecureState() {
        synchronized (RNG) {
            long[] st = {secureState};
            long v = splitmix(st);
            secureState = st[0];
            return v;
        }
    }

    static long derive(String key) {
        return Native.isLoaded() ? Native.deriveSeed(SEED, key) : (SEED * 31 + key.hashCode());
    }

    static void seedSession() {
        reseed("<session>");
    }

    /** Reseed every controlled generator from {@code derive_seed(seed, key)}. */
    static void reseed(String key) {
        if (!RANDOM) return;
        long s = derive(key);
        synchronized (RNG) {
            randomState = s;
            secureState = derive(key + "#secure");
            tlrBase = derive(key + "#tlr");
            tlrEpoch++;
        }
        JdkRandoms.reseed(s);
    }

    /** Seed for {@code new Random()} / {@code new SplittableRandom()} in code under test. */
    public static long newRandomSeed(String site) {
        if (!RANDOM) return System.nanoTime() ^ 0x5DEECE66DL ^ Thread.currentThread().getId();
        long v = nextRandomState();
        record("random", "new Random", site, "");
        return v;
    }

    public static double mathRandom(String site) {
        double d = Math.random();
        if (RANDOM) record("random", "Math.random", site, Double.toString(d));
        return d;
    }

    public static UUID randomUUID(String site) {
        UUID u = UUID.randomUUID();
        if (RANDOM) record("random", "UUID.randomUUID", site, u.toString());
        else record("entropy", "UUID.randomUUID", site, "");
        return u;
    }

    /** ThreadLocalRandom.current(): seeds this thread's generator once per test. */
    public static ThreadLocalRandom tlrCurrent(String site) {
        ThreadLocalRandom r = ThreadLocalRandom.current();
        if (RANDOM) {
            int[] seen = TLR_SEEN.get();
            if (seen[0] != tlrEpoch) {
                seen[0] = tlrEpoch;
                JdkRandoms.seedThread(Thread.currentThread(), tlrBase + 0x9E3779B97F4A7C15L * (threadNo() + 1));
                record("random", "ThreadLocalRandom.current", site, "seeded");
            }
        }
        return r;
    }

    static final ThreadLocal<int[]> TLR_SEEN = ThreadLocal.withInitial(() -> new int[] {-1});

    public static void collectionsShuffle(List<?> list, String site) {
        if (!RANDOM) {
            Collections.shuffle(list);
            return;
        }
        record("random", "Collections.shuffle", site, Integer.toString(list.size()));
        Collections.shuffle(list, new Random(nextRandomState()));
    }

    /**
     * Hook at the start of {@code SecureRandom.nextBytes(byte[])}: fills the
     * buffer from the seeded stream and returns true (the original is skipped).
     */
    public static boolean secureBytes(byte[] b) {
        if (!RANDOM || b == null) return false;
        int i = 0;
        while (i < b.length) {
            long v = nextSecureState();
            for (int k = 0; k < 8 && i < b.length; k++, i++) {
                b[i] = (byte) v;
                v >>>= 8;
            }
        }
        return true;
    }

    /** Hook for {@code SecureRandom.generateSeed(int)}: null = run the original. */
    public static byte[] secureSeed(int n) {
        if (!RANDOM || n < 0) return null;
        byte[] b = new byte[n];
        secureBytes(b);
        return b;
    }

    // ------------------------------------------------------------- filesystem
    static boolean enter() {
        int[] f = IN_HOOK.get();
        if (f[0] != 0) return false;
        f[0] = 1;
        return true;
    }

    static void exit() {
        IN_HOOK.get()[0] = 0;
    }

    /** Hook at the return of {@code File.normalizedList()} / {@code File.list()}. */
    public static String[] fsList(File dir, String[] names) {
        if (names == null || (!FS && !DEPS)) return names;
        if (!enter()) return names;
        try {
            if (FS) {
                names = names.clone();
                Arrays.sort(names);
            }
            if (TEST != null || DEPS) {
                String caller = Caller.user();
                if (caller != null) {
                    if (FS) record("fs", "File.list", caller, names.length + ":" + digestNames(Arrays.asList(names)));
                    if (DEPS) Deps.listed(dir.getPath(), names);
                }
            }
            return names;
        } finally {
            exit();
        }
    }

    static String digestNames(List<String> names) {
        StringBuilder sb = new StringBuilder();
        for (String n : names) sb.append(n).append('\n');
        return Native.isLoaded() ? Native.digest(sb.toString().getBytes(StandardCharsets.UTF_8)) : Integer.toHexString(sb.toString().hashCode());
    }

    /** Hook at the return of {@code UnixFileSystemProvider.newDirectoryStream}. */
    public static DirectoryStream<Path> fsDirStream(DirectoryStream<Path> ds, Path dir) {
        if (ds == null || (!FS && !DEPS)) return ds;
        if (!enter()) return ds;
        try {
            if (!FS && !DEPS) return ds;
            String caller = (TEST != null || DEPS) ? Caller.user() : null;
            if (!FS && caller == null) return ds;
            SortedDirectoryStream s = new SortedDirectoryStream(ds, FS);
            if (caller != null) {
                List<String> names = s.names();
                if (FS) record("fs", "Files.newDirectoryStream", caller, names.size() + ":" + digestNames(names));
                if (DEPS) Deps.listed(dir.toString(), names.toArray(new String[0]));
            }
            return s;
        } catch (IOException e) {
            return ds;
        } finally {
            exit();
        }
    }

    /** Hook at the start of FileInputStream/RandomAccessFile/FileOutputStream constructors. */
    public static void fsOpenFile(File f, String mode) {
        if (!DEPS || f == null) return;
        if (!enter()) return;
        try {
            if (Caller.user() != null) Deps.opened(f.getPath(), mode);
        } finally {
            exit();
        }
    }

    public static void fsOpenRaf(File f, String mode) {
        fsOpenFile(f, mode != null && mode.contains("w") ? "rw" : "r");
    }

    public static void fsOpenOut(File f) {
        fsOpenFile(f, "w");
    }

    public static void fsOpenIn(File f) {
        fsOpenFile(f, "r");
    }

    /** Hook at the start of {@code UnixFileSystemProvider.newByteChannel/newFileChannel}. */
    public static void nioOpen(Path p, Set<? extends OpenOption> opts) {
        if (!DEPS || p == null) return;
        if (!enter()) return;
        try {
            if (Caller.user() == null) return;
            String mode = "r";
            if (opts != null) {
                for (OpenOption o : opts) {
                    String n = o.toString();
                    if (n.equals("WRITE") || n.equals("APPEND") || n.equals("CREATE") || n.equals("CREATE_NEW")
                            || n.equals("TRUNCATE_EXISTING") || n.equals("DELETE_ON_CLOSE")) {
                        mode = "w";
                    }
                }
                if (mode.equals("w") && opts.toString().contains("READ")) mode = "rw";
            }
            Deps.opened(p.toString(), mode);
        } finally {
            exit();
        }
    }

    /** Hook at the start of existence / attribute checks. */
    public static void fsProbe(File f) {
        if (!DEPS || f == null) return;
        if (!enter()) return;
        try {
            if (Caller.user() != null) Deps.probed(f.getPath());
        } finally {
            exit();
        }
    }

    public static void nioProbe(Path p) {
        if (!DEPS || p == null) return;
        if (!enter()) return;
        try {
            if (Caller.user() != null) Deps.probed(p.toString());
        } finally {
            exit();
        }
    }

    // ---------------------------------------------------------------- network
    static boolean local(InetAddress a) {
        return a != null && (a.isLoopbackAddress() || a.isAnyLocalAddress());
    }

    static boolean isProxy(String host, int port) {
        String[][] props = {{"http.proxyHost", "http.proxyPort", "80"}, {"https.proxyHost", "https.proxyPort", "443"},
            {"socksProxyHost", "socksProxyPort", "1080"}};
        for (String[] p : props) {
            String h = System.getProperty(p[0]);
            if (h == null || h.isEmpty()) continue;
            int pp;
            try {
                pp = Integer.parseInt(System.getProperty(p[1], p[2]));
            } catch (NumberFormatException e) {
                pp = Integer.parseInt(p[2]);
            }
            if (pp == port && (h.equalsIgnoreCase(host) || (h.equals("localhost") && host.startsWith("127.")))) return true;
        }
        for (String v : new String[] {"HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"}) {
            String e = System.getenv(v);
            if (e == null || e.isEmpty()) continue;
            try {
                java.net.URI u = java.net.URI.create(e.contains("://") ? e : "http://" + e);
                int pp = u.getPort() > 0 ? u.getPort() : (v.toLowerCase(Locale.ROOT).startsWith("https") ? 443 : 80);
                String h = u.getHost();
                if (h != null && pp == port && (h.equalsIgnoreCase(host) || (h.equals("localhost") && host.startsWith("127.")))) return true;
            } catch (RuntimeException ignored) {
                // malformed proxy variable: not a proxy
            }
        }
        return false;
    }

    static boolean allowed(String host) {
        return host != null && ALLOW_HOSTS.contains(host.toLowerCase(Locale.ROOT));
    }

    /** Hook at the start of {@code Socket.connect(SocketAddress,int)} and {@code SocketChannelImpl.connect}. */
    public static void netConnect(SocketAddress sa) throws IOException {
        if ((!NET && !DEPS) || !(sa instanceof InetSocketAddress)) return;
        if (!enter()) return;
        try {
            InetSocketAddress isa = (InetSocketAddress) sa;
            InetAddress a = isa.getAddress();
            String host = isa.getHostString();
            boolean external = !(local(a) || (a == null && "localhost".equalsIgnoreCase(host)))
                    || isProxy(a != null ? a.getHostAddress() : host, isa.getPort());
            if (!external) return;
            String caller = Caller.user();
            if (caller == null) return; // infrastructure
            if (DEPS) Deps.network(host + ":" + isa.getPort());
            if (allowed(host) || (a != null && allowed(a.getHostAddress()))) {
                record("net", "connect", caller, host + ":" + isa.getPort() + ":allowed");
                return;
            }
            if (NET) {
                record("net", "connect", caller, host + ":" + isa.getPort() + ":blocked");
                throw new ConnectException("fenvix --det: network closed, connection to " + host + ":" + isa.getPort()
                        + " refused (allow it with -Dfenvix.allow.hosts=" + host + ")");
            }
        } finally {
            exit();
        }
    }

    /** Hook at the start of {@code InetAddress.getAllByName(String)} / {@code getByName}. */
    public static void dnsLookup(String host) throws UnknownHostException {
        if ((!NET && !DEPS) || host == null || host.isEmpty()) return;
        if (!enter()) return;
        try {
            String h = host.toLowerCase(Locale.ROOT);
            if (h.equals("localhost") || h.endsWith(".localhost") || h.startsWith("127.") || h.equals("::1")
                    || h.equals("[::1]") || h.equals("0.0.0.0") || Character.isDigit(h.charAt(0)) && h.matches("[0-9.]+")
                    || h.contains(":")) {
                return;
            }
            if (h.equals(localHostName())) return;
            String caller = Caller.user();
            if (caller == null) return;
            if (DEPS) Deps.network("dns:" + h);
            if (allowed(h)) {
                record("net", "dns", caller, h + ":allowed");
                return;
            }
            if (NET) {
                record("net", "dns", caller, h + ":blocked");
                throw new UnknownHostException(host + " (fenvix --det: network closed; allow it with -Dfenvix.allow.hosts=" + host + ")");
            }
        } finally {
            exit();
        }
    }

    static volatile String LOCAL_HOST_NAME;

    static String localHostName() {
        String n = LOCAL_HOST_NAME;
        if (n == null) {
            n = "";
            try {
                String e = System.getenv("HOSTNAME");
                if (e != null) n = e.toLowerCase(Locale.ROOT);
                else {
                    java.nio.file.Path p = java.nio.file.Paths.get("/etc/hostname");
                    if (java.nio.file.Files.exists(p)) n = new String(java.nio.file.Files.readAllBytes(p), StandardCharsets.UTF_8).trim().toLowerCase(Locale.ROOT);
                }
            } catch (Exception ignored) {
                // no host name
            }
            LOCAL_HOST_NAME = n;
        }
        return n;
    }

    // ------------------------------------------ environment / system properties
    public static String getenv(String name, String site) {
        String v = System.getenv(name);
        if (DEPS && name != null) Deps.env(name, v);
        return v;
    }

    public static Map<String, String> getenvAll(String site) {
        Map<String, String> m = System.getenv();
        if (!DEPS) return m;
        return new RecordingEnv(m);
    }

    public static String getProperty(String k, String site) {
        String v = System.getProperty(k);
        if (DEPS && k != null) Deps.prop(k, v);
        return v;
    }

    public static String getProperty2(String k, String def, String site) {
        String v = System.getProperty(k, def);
        if (DEPS && k != null) Deps.prop(k, System.getProperty(k));
        return v;
    }

    public static Properties getProperties(String site) {
        if (DEPS) Deps.prop("*", null);
        return System.getProperties();
    }

    public static Integer getInteger(String k, String site) {
        if (DEPS && k != null) Deps.prop(k, System.getProperty(k));
        return Integer.getInteger(k);
    }

    public static Integer getInteger2(String k, int d, String site) {
        if (DEPS && k != null) Deps.prop(k, System.getProperty(k));
        return Integer.getInteger(k, d);
    }

    public static Integer getInteger3(String k, Integer d, String site) {
        if (DEPS && k != null) Deps.prop(k, System.getProperty(k));
        return Integer.getInteger(k, d);
    }

    public static Long getLong(String k, String site) {
        if (DEPS && k != null) Deps.prop(k, System.getProperty(k));
        return Long.getLong(k);
    }

    public static Long getLong2(String k, long d, String site) {
        if (DEPS && k != null) Deps.prop(k, System.getProperty(k));
        return Long.getLong(k, d);
    }

    public static Long getLong3(String k, Long d, String site) {
        if (DEPS && k != null) Deps.prop(k, System.getProperty(k));
        return Long.getLong(k, d);
    }

    public static boolean getBoolean(String k, String site) {
        if (DEPS && k != null) Deps.prop(k, System.getProperty(k));
        return Boolean.getBoolean(k);
    }

    // ------------------------------------------------------------ coverage
    /** Per-class touch probe (skip-with-proof capture). */
    public static void touch(int classId) {
        Deps.touch(classId);
    }

    public static void touchStatic(int classId) {
        Deps.touchStaticRead(classId);
    }

    public static void writeStatic(int classId) {
        Deps.wroteStatic(classId);
    }

    static Field field(Class<?> c, String name) {
        try {
            Field f = c.getDeclaredField(name);
            f.setAccessible(true);
            return f;
        } catch (Throwable t) {
            return null;
        }
    }
}
