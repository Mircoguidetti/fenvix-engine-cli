package dev.fenvix.rt;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.PriorityQueue;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.concurrent.AbstractExecutorService;
import java.util.concurrent.Callable;
import java.util.concurrent.Delayed;
import java.util.concurrent.Executors;
import java.util.concurrent.FutureTask;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.RunnableScheduledFuture;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/**
 * Scheduled executor on virtual time (returned by Executors.newScheduledThreadPool
 * and newSingleThreadScheduledExecutor in code under test, under --det).
 *
 * <p>Tasks are ordered by (virtual due time, creation order). A dispatcher
 * thread fires the earliest task; when it is not yet due and every other thread
 * of the test is idle (waiting without a timeout, or inside a rewritten timed
 * wait), the virtual clock jumps to its due time and the task fires at once
 * ("fast"), one task at a time. While another thread is working the dispatcher
 * waits for real, in slices, so that work can finish first (the analogue of the
 * Node rule "timers wait for real while I/O is pending"). A per-test budget of
 * fast firings bounds periodic tasks that are never cancelled.
 */
final class VirtualScheduler extends AbstractExecutorService implements ScheduledExecutorService {
    private static final Set<Thread> DISPATCHERS = Collections.synchronizedSet(Collections.newSetFromMap(new WeakHashMap<>()));
    private static int count;

    static boolean isDispatcher(Thread t) {
        return DISPATCHERS.contains(t);
    }

    private final ThreadPoolExecutor workers;
    private final PriorityQueue<Task<?>> queue = new PriorityQueue<>();
    private final Object lock = new Object();
    private final Thread dispatcher;
    private final String site;
    private volatile boolean shutdown;
    private long seq;
    private int running;

    VirtualScheduler(int n, ThreadFactory tf, String site) {
        this.site = site;
        ThreadFactory f = tf != null ? tf : Executors.defaultThreadFactory();
        this.workers = new ThreadPoolExecutor(n, n, 0L, TimeUnit.MILLISECONDS, new LinkedBlockingQueue<>(), f);
        int id;
        synchronized (VirtualScheduler.class) {
            id = ++count;
        }
        dispatcher = new Thread(this::loop, "fenvix-scheduler-" + id);
        dispatcher.setDaemon(true);
        DISPATCHERS.add(dispatcher);
        dispatcher.start();
    }

    final class Task<V> extends FutureTask<V> implements RunnableScheduledFuture<V> {
        long due;
        final long order;
        final long period; // 0 one-shot, >0 fixed rate, <0 fixed delay

        Task(Callable<V> c, long due) {
            super(c);
            this.due = due;
            this.period = 0;
            this.order = nextSeq();
        }

        Task(Runnable r, V v, long due, long period) {
            super(r, v);
            this.due = due;
            this.period = period;
            this.order = nextSeq();
        }

        @Override
        public long getDelay(TimeUnit unit) {
            return unit.convert(due - Det.monoNow(), TimeUnit.NANOSECONDS);
        }

        @Override
        public int compareTo(Delayed o) {
            if (o == this) return 0;
            if (o instanceof Task) {
                Task<?> t = (Task<?>) o;
                int c = Long.compare(due, t.due);
                return c != 0 ? c : Long.compare(order, t.order);
            }
            return Long.compare(getDelay(TimeUnit.NANOSECONDS), o.getDelay(TimeUnit.NANOSECONDS));
        }

        @Override
        public boolean isPeriodic() {
            return period != 0;
        }

        @Override
        public void run() {
            try {
                if (!isPeriodic()) {
                    super.run();
                } else if (runAndReset() && !shutdown) {
                    due = period > 0 ? due + period : Det.monoNow() + (-period);
                    enqueue(this);
                }
            } finally {
                synchronized (lock) {
                    running--;
                    lock.notifyAll();
                }
            }
        }

        @Override
        public boolean cancel(boolean mayInterrupt) {
            boolean c = super.cancel(mayInterrupt);
            synchronized (lock) {
                queue.remove(this);
                lock.notifyAll();
            }
            return c;
        }
    }

    private long nextSeq() {
        synchronized (lock) {
            return seq++;
        }
    }

    private <T> Task<T> enqueue(Task<T> t) {
        synchronized (lock) {
            if (shutdown && !t.isPeriodic() && t.due > Det.monoNow() && false) throw new RejectedExecutionException();
            queue.add(t);
            lock.notifyAll();
        }
        return t;
    }

    private void loop() {
        long waitedFor = -1, waitedNs = 0;
        try {
            while (true) {
                Task<?> t;
                synchronized (lock) {
                    while (queue.isEmpty() && !(shutdown && running == 0)) lock.wait();
                    if (queue.isEmpty()) break;
                    t = queue.peek();
                }
                long now = Det.monoNow();
                if (t.due > now) {
                    long remaining = t.due - now;
                    if (waitedFor != t.order) {
                        waitedFor = t.order;
                        waitedNs = 0;
                    }
                    boolean idle;
                    synchronized (lock) {
                        idle = running == 0;
                    }
                    if (waitedNs < remaining && !(idle && settled(t.due) && Det.takeFastFiring())) {
                        long slice = Math.min(remaining - waitedNs, 10_000_000L);
                        long t0 = System.nanoTime();
                        synchronized (lock) {
                            lock.wait(Math.max(1, slice / 1_000_000L));
                        }
                        waitedNs += System.nanoTime() - t0;
                        continue;
                    }
                    Det.advanceTo(t.due);
                }
                synchronized (lock) {
                    if (queue.peek() != t) continue; // cancelled or an earlier task arrived
                    queue.poll();
                    running++;
                }
                waitedFor = -1;
                Det.record("sched", "sched.timer", site, "0/1:" + site + "#" + t.order);
                try {
                    workers.execute(t);
                } catch (RejectedExecutionException e) {
                    synchronized (lock) {
                        running--;
                    }
                    t.cancel(false);
                }
            }
        } catch (InterruptedException ignored) {
            // shutdownNow
        } finally {
            workers.shutdown();
        }
    }

    /**
     * Quiet twice, 2 ms apart: a thread just woken by the previous task (a latch
     * count-down) still shows as waiting until it runs; the second look lets it run.
     */
    private boolean settled(long due) throws InterruptedException {
        if (!Det.quietUntil(dispatcher, due)) return false;
        Thread.sleep(2);
        return Det.quietUntil(dispatcher, due);
    }

    // ------------------------------------------------------------ ScheduledExecutorService
    @Override
    public ScheduledFuture<?> schedule(Runnable command, long delay, TimeUnit unit) {
        check(command);
        return enqueue(new Task<Void>(command, null, Det.monoNow() + Math.max(0, unit.toNanos(delay)), 0));
    }

    @Override
    public <V> ScheduledFuture<V> schedule(Callable<V> callable, long delay, TimeUnit unit) {
        check(callable);
        return enqueue(new Task<>(callable, Det.monoNow() + Math.max(0, unit.toNanos(delay))));
    }

    @Override
    public ScheduledFuture<?> scheduleAtFixedRate(Runnable command, long initialDelay, long period, TimeUnit unit) {
        check(command);
        if (period <= 0) throw new IllegalArgumentException();
        return enqueue(new Task<Void>(command, null, Det.monoNow() + Math.max(0, unit.toNanos(initialDelay)), unit.toNanos(period)));
    }

    @Override
    public ScheduledFuture<?> scheduleWithFixedDelay(Runnable command, long initialDelay, long delay, TimeUnit unit) {
        check(command);
        if (delay <= 0) throw new IllegalArgumentException();
        return enqueue(new Task<Void>(command, null, Det.monoNow() + Math.max(0, unit.toNanos(initialDelay)), -unit.toNanos(delay)));
    }

    private void check(Object o) {
        if (o == null) throw new NullPointerException();
        if (shutdown) throw new RejectedExecutionException("fenvix virtual scheduler is shut down");
    }

    @Override
    public void execute(Runnable command) {
        schedule(command, 0, TimeUnit.NANOSECONDS);
    }

    @Override
    public void shutdown() {
        synchronized (lock) {
            shutdown = true;
            queue.removeIf(Task::isPeriodic);
            lock.notifyAll();
        }
    }

    @Override
    public List<Runnable> shutdownNow() {
        List<Runnable> left;
        synchronized (lock) {
            shutdown = true;
            left = new ArrayList<>(queue);
            queue.clear();
            lock.notifyAll();
        }
        dispatcher.interrupt();
        left.addAll(workers.shutdownNow());
        return left;
    }

    @Override
    public boolean isShutdown() {
        return shutdown;
    }

    @Override
    public boolean isTerminated() {
        return shutdown && !dispatcher.isAlive() && workers.isTerminated();
    }

    @Override
    public boolean awaitTermination(long timeout, TimeUnit unit) throws InterruptedException {
        long deadline = System.nanoTime() + unit.toNanos(timeout);
        dispatcher.join(Math.max(1, unit.toMillis(timeout)));
        long left = deadline - System.nanoTime();
        return !dispatcher.isAlive() && workers.awaitTermination(Math.max(0, left), TimeUnit.NANOSECONDS);
    }
}
