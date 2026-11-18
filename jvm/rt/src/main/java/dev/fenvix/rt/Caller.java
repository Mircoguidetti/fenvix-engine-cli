package dev.fenvix.rt;

import java.util.Optional;

/**
 * The first stack frame outside the JDK and fenvix, as {@code path:line}; null
 * when that frame belongs to the test infrastructure (or there is none).
 */
final class Caller {
    private Caller() {}

    private static final StackWalker WALKER = StackWalker.getInstance(StackWalker.Option.RETAIN_CLASS_REFERENCE);

    static String user() {
        Optional<StackWalker.StackFrame> f = WALKER.walk(s -> s.filter(fr -> {
            Class<?> c = fr.getDeclaringClass();
            ClassLoader l = c.getClassLoader();
            if (l == null || l == ClassLoader.getPlatformClassLoader()) return false;
            String n = c.getName();
            return !n.startsWith("dev.fenvix.") && !n.startsWith("jdk.") && !n.startsWith("sun.");
        }).findFirst());
        if (!f.isPresent()) return null;
        StackWalker.StackFrame fr = f.get();
        String n = fr.getClassName();
        if (Infra.isInfraDotted(n)) return null;
        String pkg = n.lastIndexOf('.') >= 0 ? n.substring(0, n.lastIndexOf('.')).replace('.', '/') + "/" : "";
        String file = fr.getFileName() != null ? fr.getFileName() : n.substring(n.lastIndexOf('.') + 1) + ".java";
        return pkg + file + ":" + fr.getLineNumber();
    }
}
