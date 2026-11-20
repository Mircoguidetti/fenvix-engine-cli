package rv;

import java.util.List;
import java.util.Optional;
import java.util.function.Function;

/**
 * Static state that cannot change after class initialisation, of the kinds the shared-state rule
 * classifies as mutable (cost probes for review R-022b, jvm/test/run_r022b_cost_probe.py).
 */
public final class Cost {
    public enum Color { RED, GREEN, BLUE }

    /** Non-final classes whose instances only have final fields (deeply immutable at run time). */
    public static class Inner {
        final int x;
        Inner(int x) { this.x = x; }
        public int x() { return x; }
    }

    public static class Holder {
        final Inner inner;
        Holder(Inner inner) { this.inner = inner; }
        public int x() { return inner.x(); }
    }

    public static final List<String> NAMES = List.of("a", "b");
    public static final Optional<String> OPT = Optional.of("x");
    public static final Holder HOLDER = new Holder(new Inner(1));
    public static final Function<String, Integer> LEN = String::length;

    private Cost() {}

    /** javac compiles this switch to a lookup in the synthetic array Cost$1.$SwitchMap$rv$Cost$Color. */
    public static String name(Color c) {
        switch (c) {
            case RED: return "r";
            case GREEN: return "g";
            default: return "b";
        }
    }
}
