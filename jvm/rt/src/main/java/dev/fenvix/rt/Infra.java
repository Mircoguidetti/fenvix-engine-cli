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

    /**
     * Classes seen by the agent's transformer (dotted name -> infrastructure?), decided by
     * code source ({@link #decide}). The package prefixes above are only a fallback for
     * classes the transformer never saw (R-022 S11: a repository whose own code lives under
     * org/codehaus/plexus/, org/apache/maven/, org/junit/... is code under test).
     */
    static final java.util.concurrent.ConcurrentHashMap<String, Boolean> KNOWN = new java.util.concurrent.ConcurrentHashMap<>();

    /** Record the transformer's decision for a class (internal name). */
    public static void known(String internalName, boolean infra) {
        if (internalName != null) KNOWN.put(internalName.replace('/', '.'), infra);
    }

    /** The transformer's decision for a class (internal name), or null when it never saw it. */
    public static Boolean knownInfra(String internalName) {
        return internalName == null ? null : KNOWN.get(internalName.replace('/', '.'));
    }

    /**
     * Infrastructure by code source: fenvix itself, the build tool's distribution and the
     * test runner's own jars (JUnit, Surefire, TestNG, JaCoCo, IDE runners). Classes from
     * a directory (the project's build output) or from any other jar are code under test,
     * whatever their package.
     */
    public static boolean decide(String internalName, String codeSource) {
        if (internalName == null) return true;
        if (internalName.startsWith("dev/fenvix/")) return true;
        if (codeSource == null || codeSource.isEmpty()) return false; // generated at run time
        if (isToolDistribution(codeSource)) return true;
        String p = codeSource.replace('\\', '/');
        if (!p.endsWith(".jar")) return false;
        String f = p.substring(p.lastIndexOf('/') + 1);
        if (f.startsWith("kotlin-stdlib")) return internalName.startsWith("kotlin/jvm/internal/Intrinsics");
        for (String j : RUNNER_JARS) {
            if (f.startsWith(j)) return true;
        }
        // junit-4.13.2.jar, junit-3.8.1.jar (not junit-addons, junit-dataprovider, ...)
        if (f.startsWith("junit-") && f.length() > 6 && Character.isDigit(f.charAt(6))) return true;
        return false;
    }

    /** File-name prefixes of the test runner's jars. */
    static final String[] RUNNER_JARS = {
        "junit-platform-", "junit-jupiter-", "junit-vintage-", "opentest4j-", "apiguardian-api-",
        "surefire-", "common-java5-", "common-junit3-", "common-junit4-", "common-junit48-", "maven-surefire-common-",
        "testng-", "org.jacoco.agent", "jacocoagent", "idea_rt", "junit-rt", "byte-buddy-agent-", "pitest",
        "fenvix-agent",
    };

    /** True for an internal (slash) class name that belongs to the infrastructure. */
    public static boolean isInfra(String internalName) {
        if (internalName == null) return true;
        Boolean k = knownInfra(internalName);
        if (k != null) return k;
        for (String p : PREFIXES) {
            if (internalName.startsWith(p)) return true;
        }
        return false;
    }

    /**
     * A code source inside the build tool's own distribution (Gradle's lib/ and
     * worker jars, the Gradle wrapper's distributions): infrastructure whatever
     * the package name (Gradle bundles kryo, slf4j, native-platform, ...). Its
     * version is part of the runtime identity instead.
     */
    public static boolean isToolDistribution(String path) {
        if (path == null) return false;
        return (path.contains("/gradle-") && path.contains("/lib/")) || path.contains("/.gradle/caches/") && path.contains("/workerMain/")
                || path.contains("/.gradle/wrapper/dists/") || path.contains("/generated-gradle-jars/")
                || path.contains("/org/apache/maven/surefire/");
    }

    /** Same test for a binary (dot-separated) class name. */
    public static boolean isInfraDotted(String className) {
        if (className == null) return true;
        Boolean k = KNOWN.get(className);
        if (k != null) return k;
        return isInfra(className.replace('.', '/'));
    }

    /** JDK classes: loaded by the bootstrap or platform class loader. */
    public static boolean isJdk(Class<?> c) {
        ClassLoader l = c.getClassLoader();
        return l == null || l == Compat.platformLoader();
    }
}
