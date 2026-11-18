package dev.fenvix.junit;

import dev.fenvix.rt.Det;
import dev.fenvix.rt.Deps;
import dev.fenvix.rt.Lifecycle;
import java.io.File;
import java.lang.management.ManagementFactory;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.platform.engine.TestExecutionResult;
import org.junit.platform.launcher.TestExecutionListener;
import org.junit.platform.launcher.TestIdentifier;
import org.junit.platform.launcher.TestPlan;

/**
 * JUnit Platform listener (registered through ServiceLoader from the agent
 * jar): brackets every test for Level 0 (reseed, wall clock reset,
 * fingerprint) and for the skip-with-proof capture, and writes one trace part
 * per test plan. Engine-agnostic: Jupiter, Vintage (JUnit 4) and other
 * Platform engines get the same brackets.
 */
public class FenvixListener implements TestExecutionListener {
    static final AtomicInteger PLANS = new AtomicInteger();
    private final boolean on;
    private TestPlan plan;
    private int index;
    private String module = "";

    public FenvixListener() {
        boolean ok;
        try {
            ok = Det.ON || Det.DEPS;
        } catch (Throwable t) {
            ok = false; // agent not installed in this JVM
        }
        on = ok;
    }

    static String runnerVersion() {
        Package p = TestPlan.class.getPackage();
        return p != null && p.getImplementationVersion() != null ? p.getImplementationVersion() : "";
    }

    @Override
    public void testPlanExecutionStarted(TestPlan testPlan) {
        if (!on) return;
        Flags.platformActive = true;
        plan = testPlan;
        module = Ids.module(System.getProperty("fenvix.module", ""));
        List<String> order = new ArrayList<>();
        for (TestIdentifier root : testPlan.getRoots()) collect(testPlan, root, order);
        if (Det.ON) {
            String out = System.getProperty("fenvix.out", ".fenvix");
            String pid = dev.fenvix.rt.Compat.pid();
            int n = PLANS.incrementAndGet();
            String name = System.currentTimeMillis() + "-" + (module.isEmpty() ? "root" : module.replace('/', '_')) + "-" + pid + "-" + n;
            File part = new File(out, "parts/" + name + ".jsonl");
            if (n > 1) Det.closeTrace();
            String engines = engines(testPlan);
            Det.openTrace(part.getPath(), Lifecycle.metaJson(engines, runnerVersion(),
                    "one JVM per build module, serial (no parallel forks, no parallel JUnit execution)"), order.toArray(new String[0]));
        }
    }

    static String engines(TestPlan p) {
        List<String> e = new ArrayList<>();
        for (TestIdentifier r : p.getRoots()) {
            String u = r.getUniqueId();
            int c = u.indexOf(':');
            int close = u.indexOf(']');
            if (c > 0 && close > c) e.add(u.substring(c + 1, close));
        }
        return String.join("+", e);
    }

    private void collect(TestPlan p, TestIdentifier id, List<String> out) {
        if (id.isTest()) out.add(Ids.fromUniqueId(id.getUniqueId(), module));
        for (TestIdentifier c : p.getChildren(id)) collect(p, c, out);
    }

    @Override
    public void testPlanExecutionFinished(TestPlan testPlan) {
        if (!on) return;
        Flags.platformActive = false;
        if (Det.ON) Det.closeTrace();
    }

    @Override
    public void executionStarted(TestIdentifier id) {
        if (!on) return;
        if (id.isTest()) {
            Det.beginTest(Ids.fromUniqueId(id.getUniqueId(), module), index++);
        } else if (id.getParentId().isPresent()) {
            Deps.beginContainer(Ids.fromUniqueId(id.getUniqueId(), module));
        }
    }

    @Override
    public void executionFinished(TestIdentifier id, TestExecutionResult result) {
        if (!on) return;
        if (id.isTest()) {
            Det.endTest(outcome(result));
        } else if (id.getParentId().isPresent()) {
            Deps.endContainer();
        }
    }

    @Override
    public void executionSkipped(TestIdentifier id, String reason) {
        if (!on || !id.isTest()) return;
        Det.beginTest(Ids.fromUniqueId(id.getUniqueId(), module), index++);
        Det.endTest("skipped");
    }

    static String outcome(TestExecutionResult r) {
        switch (r.getStatus()) {
            case SUCCESSFUL:
                return "passed";
            case ABORTED:
                return "skipped";
            default:
                return "failed";
        }
    }
}
