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
        try {
            Method m = child.getClass().getMethod("getName");
            return String.valueOf(m.invoke(child));
        } catch (Exception e) {
            try {
                Method m = child.getClass().getMethod("getDescription");
                return String.valueOf(((Description) m.invoke(child)).getDisplayName());
            } catch (Exception e2) {
                return String.valueOf(child);
            }
        }
    }

    /** Children of a ParentRunner, reordered with a non-zero seed (group key = the runner's description). */
    public static Collection<?> order(Object runner, Collection<?> children) {
        try {
            if (!Det.ON || Order.seed() == 0 || children == null || children.size() < 2) return children;
            String group;
            try {
                group = ((org.junit.runner.Runner) runner).getDescription().getDisplayName();
            } catch (Throwable t) {
                group = runner.getClass().getName();
            }
            List<Object> l = new ArrayList<>(children);
            List<String> names = new ArrayList<>();
            for (Object c : l) names.add(key(c));
            List<String> sorted = new ArrayList<>(names);
            sorted.sort(Comparator.naturalOrder());
            Map<String, Integer> rank = Order.rank(sorted, Order.seed(), group);
            l.sort(Comparator.comparingInt((Object c) -> rank.getOrDefault(key(c), Integer.MAX_VALUE)));
            return l;
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
