package dev.fenvix.agent;

import dev.fenvix.rt.Det;
import dev.fenvix.rt.Lifecycle;
import dev.fenvix.rt.Native;
import java.lang.instrument.Instrumentation;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Second stage of the agent: runs once the runtime is on the bootstrap class path. */
final class Installer {
    private Installer() {}

    static void setIfAbsent(String k, String v) {
        if (System.getProperty(k) == null) System.setProperty(k, v);
    }

    static void install(Instrumentation inst, Path dir) throws Exception {
        Native.load(System.getProperty("fenvix.native"));
        if (dev.fenvix.rt.Compat.javaMajor() >= 9) Modules.open(inst);
        Det.configure();
        if (!Det.ON && !Det.DEPS) return;
        if (Det.ON) {
            // JUnit Jupiter configuration parameters (system properties are a source of them)
            setIfAbsent("junit.jupiter.testclass.order.default", "dev.fenvix.junit.DetClassOrderer");
            System.setProperty("junit.jupiter.testmethod.order.default", "dev.fenvix.junit.DetMethodOrderer");
            System.setProperty("junit.jupiter.testclass.order.default", "dev.fenvix.junit.DetClassOrderer");
            // @TestMethodOrder(MethodOrderer.Random.class) and friends: a fixed seed
            System.setProperty("junit.jupiter.execution.order.random.seed", String.valueOf(Det.SEED));
            System.setProperty("junit.jupiter.execution.parallel.enabled", "false");
        }
        inst.addTransformer(new CallSiteRewriter(), false);
        inst.addTransformer(new RunnerHooks(), false);
        JdkHooks hooks = new JdkHooks();
        inst.addTransformer(hooks, true);
        List<Class<?>> targets = new ArrayList<>();
        for (String n : JdkHooks.targets()) {
            try {
                targets.add(Class.forName(n, false, null));
            } catch (Throwable ignored) {
                // not in this JDK
            }
        }
        if (!targets.isEmpty()) {
            try {
                inst.retransformClasses(targets.toArray(new Class<?>[0]));
            } catch (Throwable t) {
                System.err.println("fenvix: JDK hooks not installed: " + t);
            }
        }
        System.setProperty("fenvix.meta.jdkhooks", String.join(",", hooks.installed()));
        Lifecycle.installShutdownHook();
    }
}
