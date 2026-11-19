package rd;

/** Process-wide mode, set once (like json-iterator's JsoniterSpi / dynamic codegen mode). */
public final class Mode {
    private static String current;

    private Mode() {}

    public static synchronized void enable(String m) {
        if (current != null && !current.equals(m)) throw new IllegalStateException("mode already set to " + current);
        current = m;
    }

    public static synchronized String current() {
        return current == null ? "default" : current;
    }
}
