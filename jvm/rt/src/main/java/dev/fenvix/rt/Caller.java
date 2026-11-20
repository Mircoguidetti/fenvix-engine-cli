package dev.fenvix.rt;

/**
 * Who made a call: the first stack frame outside the JDK and fenvix. Uses the
 * Throwable stack trace (Java 8 compatible); JDK frames are told by package,
 * infrastructure frames by {@link Infra} (code source of the class, decided by
 * the agent's transformer).
 */
final class Caller {
    private Caller() {}

    /** No non-JDK frame (or only fenvix). */
    static final int NONE = 0;
    /** The first non-JDK frame is code under test. */
    static final int USER = 1;
    /** The first non-JDK frame is test infrastructure (runner, build tool). */
    static final int INFRA = 2;
    /** The call comes from class loading (the class digests cover it). */
    static final int LOADING = 3;

    static boolean jdk(String n) {
        return n.startsWith("java.") || n.startsWith("javax.") || n.startsWith("jdk.") || n.startsWith("sun.")
                || n.startsWith("com.sun.") || n.startsWith("dev.fenvix.");
    }

    static boolean loading(String m) {
        return m.equals("loadClass") || m.equals("findClass") || m.equals("defineClass") || m.equals("loadClassOrNull")
                || m.equals("findBootstrapClassOrNull") || m.equals("defineClass1");
    }

    /**
     * Kind of the caller. With {@code lookup} the call is itself a class lookup
     * (Class.forName, ClassLoader.loadClass): loading frames above the first
     * non-JDK frame are the lookup, not class loading triggered by the code.
     */
    static int kind(boolean lookup) {
        StackTraceElement[] st = new Throwable().getStackTrace();
        for (StackTraceElement e : st) {
            String n = e.getClassName();
            if (!lookup && loading(e.getMethodName())) return LOADING;
            if (jdk(n)) continue;
            return Infra.isInfraDotted(n) ? INFRA : USER;
        }
        return NONE;
    }

    static int kind() {
        return kind(false);
    }

    /** {@code path:line} of the calling code under test, or null when the caller is not code under test. */
    static String user() {
        StackTraceElement[] st = new Throwable().getStackTrace();
        for (StackTraceElement e : st) {
            if (loading(e.getMethodName())) return null; // class loading triggered by the code
            String n = e.getClassName();
            if (jdk(n)) continue;
            if (Infra.isInfraDotted(n)) return null;
            String pkg = n.lastIndexOf('.') >= 0 ? n.substring(0, n.lastIndexOf('.')).replace('.', '/') + "/" : "";
            String file = e.getFileName() != null ? e.getFileName() : n.substring(n.lastIndexOf('.') + 1) + ".java";
            return pkg + file + ":" + e.getLineNumber();
        }
        return null;
    }
}
