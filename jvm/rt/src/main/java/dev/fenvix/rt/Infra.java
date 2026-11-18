package dev.fenvix.rt;

/**
 * Classes that are test infrastructure, not code under test: the test runner,
 * the build tool's worker, coverage agents and fenvix itself. Their call sites
 * are never rewritten (they keep real time, real randomness) and their
 * filesystem and network activity is not recorded, mirroring the Python shell
 * (pytest plugins keep real timers) and the Node shell (runner frames).
 */
public final class Infra {
    private Infra() {}

    /** Internal (slash-separated) name prefixes. */
    static final String[] PREFIXES = {
        "dev/fenvix/",
        "org/junit/platform/",
        "org/junit/jupiter/engine/",
        "org/junit/jupiter/api/",
        "org/junit/jupiter/params/",
        "org/junit/vintage/",
        "org/junit/runner/",
        "org/junit/internal/",
        "junit/runner/",
        "junit/textui/",
        "org/opentest4j/",
        "org/apiguardian/",
        "org/gradle/",
        "worker/org/gradle/",
        "org/apache/maven/",
        "org/codehaus/plexus/",
        "org/jacoco/",
        "com/intellij/rt/",
        "org/testng/",
        "kotlin/jvm/internal/Intrinsics", // pure null checks, very hot
        "net/bytebuddy/agent/",
        "org/pitest/",
    };

    /** True for an internal (slash) class name that belongs to the infrastructure. */
    public static boolean isInfra(String internalName) {
        if (internalName == null) return true;
        for (String p : PREFIXES) {
            if (internalName.startsWith(p)) return true;
        }
        return false;
    }

    /** Same test for a binary (dot-separated) class name. */
    public static boolean isInfraDotted(String className) {
        return className == null || isInfra(className.replace('.', '/'));
    }

    /** JDK classes: loaded by the bootstrap or platform class loader. */
    public static boolean isJdk(Class<?> c) {
        ClassLoader l = c.getClassLoader();
        return l == null || l == ClassLoader.getPlatformClassLoader();
    }
}
