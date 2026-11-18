package dev.fenvix.rt;

/**
 * The first stack frame outside the JDK and fenvix, as {@code path:line}; null
 * when that frame belongs to the test infrastructure, when the call comes from
 * class loading (the class digests cover it), or when there is none. Uses the
 * Throwable stack trace (Java 8 compatible); JDK frames are told by package.
 */
final class Caller {
    private Caller() {}

    static boolean jdk(String n) {
        return n.startsWith("java.") || n.startsWith("javax.") || n.startsWith("jdk.") || n.startsWith("sun.")
                || n.startsWith("com.sun.") || n.startsWith("dev.fenvix.");
    }

    static String user() {
        StackTraceElement[] st = new Throwable().getStackTrace();
        for (StackTraceElement e : st) {
            String m = e.getMethodName();
            if (m.equals("loadClass") || m.equals("findClass") || m.equals("defineClass") || m.equals("loadClassOrNull")
                    || m.equals("findBootstrapClassOrNull") || m.equals("defineClass1")) {
                return null; // class loading triggered by the code
            }
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
