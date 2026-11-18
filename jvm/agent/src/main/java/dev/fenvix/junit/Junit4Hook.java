package dev.fenvix.junit;

import dev.fenvix.rt.Det;
import dev.fenvix.rt.Deps;
import dev.fenvix.rt.Lifecycle;
import java.io.File;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;
import org.junit.runner.notification.RunNotifier;

/**
 * JUnit 4 side of the shell (called from the runner hooks): per-test brackets
 * through a RunListener attached to every RunNotifier, and the seeded shuffle
 * of ParentRunner children. Silent while a JUnit Platform plan runs (the
 * Vintage engine creates its own RunNotifier; the Platform listener brackets
 * those tests).
 */
public final class Junit4Hook {
    private Junit4Hook() {}

    
    static final Listener LISTENER = new Listener();
    static final Map<Object, Boolean> ATTACHED = new java.util.WeakHashMap<>();

    public static void attach(Object notifier) {
        try {
            if (!(Det.ON || Det.DEPS)) return;
            synchronized (ATTACHED) {
                if (ATTACHED.put(notifier, Boolean.TRUE) != null) return;
            }
            ((RunNotifier) notifier).addListener(LISTENER);
        } catch (Throwable t) {
            if (Boolean.getBoolean("fenvix.debug")) t.printStackTrace();
        }
    }

    static String key(Object child) {
        if (child instanceof org.junit.runners.model.FrameworkMethod) {
            return ((org.junit.runners.model.FrameworkMethod) child).getName();
        }
        if (child instanceof org.junit.runner.Describable) {
            return String.valueOf(((org.junit.runner.Describable) child).getDescription().getDisplayName());
        }
        return String.valueOf(child);
    }

    /** ParentRunner caches its children collection; its reordering is cached by identity (called many times). */
    static final Map<Integer, Object[]> ORDERED = new java.util.HashMap<>();

    public static Collection<?> order(Object runner, Collection<?> children) {
        if (!Det.ON || Order.seed() == 0 || children == null || children.size() < 2) return children;
        int key = System.identityHashCode(children);
        synchronized (ORDERED) {
            Object[] hit = ORDERED.get(key);
            if (hit != null && ((java.lang.ref.WeakReference<?>) hit[0]).get() == children) return (Collection<?>) hit[1];
        }
        Collection<?> r = computeOrder(runner, children);
        synchronized (ORDERED) {
            ORDERED.put(key, new Object[] {new java.lang.ref.WeakReference<Object>(children), r});
        }
        return r;
    }

    static Collection<?> computeOrder(Object runner, Collection<?> children) {
        try {
            String group;
            try {
                group = ((org.junit.runner.Runner) runner).getDescription().getDisplayName();
            } catch (Throwable t) {
                group = runner.getClass().getName();
            }
            List<Object> l = new ArrayList<>(children);
            Map<Object, String> keys = new java.util.IdentityHashMap<>();
            for (Object c : l) keys.put(c, key(c));
            List<String> sorted = new ArrayList<>(keys.values());
            sorted.sort(Comparator.naturalOrder());
            Map<String, Integer> rank = Order.rank(sorted, Order.seed(), group);
            l.sort(Comparator.comparingInt((Object c) -> rank.getOrDefault(keys.get(c), Integer.MAX_VALUE)));
            return java.util.Collections.unmodifiableList(l);
        } catch (Throwable t) {
            return children;
        }
    }

    static String id(Description d) {
        String cls = d.getClassName();
        String m = d.getMethodName();
        String mod = Ids.module(System.getProperty("fenvix.module", ""));
        String id = cls + "::" + (m == null ? d.getDisplayName() : m);
        return mod.isEmpty() ? id : mod + "::" + id;
    }

    static final class Listener extends RunListener {
        boolean opened;
        String current;
        String outcome;
        int index;

        @Override
        public synchronized void testRunStarted(Description d) {
            if (Flags.platformActive || opened || !Det.ON) return;
            opened = true;
            List<String> order = new ArrayList<>();
            collect(d, order);
            String out = System.getProperty("fenvix.out", ".fenvix");
            String mod = Ids.module(System.getProperty("fenvix.module", ""));
            String name = System.currentTimeMillis() + "-" + (mod.isEmpty() ? "root" : mod.replace('/', '_')) + "-"
                    + dev.fenvix.rt.Compat.pid() + "-j4";
            Det.openTrace(new File(out, "parts/" + name + ".jsonl").getPath(),
                    Lifecycle.metaJson("junit4", junitVersion(), "one JVM per build module, serial"), order.toArray(new String[0]));
        }

        static String junitVersion() {
            try {
                return junit.runner.Version.id();
            } catch (Throwable t) {
                return "";
            }
        }

        void collect(Description d, List<String> out) {
            if (d.isTest()) out.add(id(d));
            for (Description c : d.getChildren()) collect(c, out);
        }

        void ensureOpen() {
            if (!opened && Det.ON) testRunStarted(Description.EMPTY);
        }

        @Override
        public synchronized void testSuiteStarted(Description d) {
            if (Flags.platformActive) return;
            if (d.getClassName() != null) Deps.beginContainer(d.getClassName());
        }

        @Override
        public synchronized void testSuiteFinished(Description d) {
            if (Flags.platformActive) return;
            if (d.getClassName() != null) Deps.endContainer();
        }

        @Override
        public synchronized void testStarted(Description d) {
            if (Flags.platformActive) return;
            ensureOpen();
            String id = id(d);
            if (id.equals(current)) return;
            if (current != null) Det.endTest(outcome);
            current = id;
            outcome = "passed";
            Det.beginTest(id, index++);
        }

        @Override
        public synchronized void testFailure(Failure f) {
            if (Flags.platformActive) return;
            if (current != null && id(f.getDescription()).equals(current)) outcome = "failed";
        }

        @Override
        public synchronized void testAssumptionFailure(Failure f) {
            if (Flags.platformActive) return;
            if (current != null && id(f.getDescription()).equals(current) && !"failed".equals(outcome)) outcome = "skipped";
        }

        @Override
        public synchronized void testFinished(Description d) {
            if (Flags.platformActive) return;
            if (current != null && id(d).equals(current)) {
                Det.endTest(outcome);
                current = null;
            }
        }

        @Override
        public synchronized void testIgnored(Description d) {
            if (Flags.platformActive) return;
            ensureOpen();
            Det.beginTest(id(d), index++);
            Det.endTest("skipped");
        }

        @Override
        public void testRunFinished(Result r) {
            // the trace is closed at JVM exit (several runs may share one JVM)
        }
    }
}
