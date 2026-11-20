package nw;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;
import java.util.function.IntSupplier;

/**
 * Static state for the immutability refinements of the shared-state rule (jvm/test/run_r022b_narrowing.py).
 * Each refinement has an immutable case (its reader must not be `mut`) and a mutable twin of the same
 * shape (a writer test changes it; its reader must run again).
 */
public final class State {
    private State() {}

    // R1: deep check of the runtime value over final fields (non-final classes included)
    public static class Inner {
        final int x;
        Inner(int x) { this.x = x; }
    }

    public static class Holder {
        final Inner inner;
        final String name;
        Holder(Inner inner, String name) { this.inner = inner; this.name = name; }
        public int x() { return inner.x; }
    }

    public static class Box {
        final List<String> items;
        Box(List<String> items) { this.items = items; }
        public List<String> items() { return items; }
    }

    /** declared type Holder, runtime class with a mutable field */
    public static class Sub extends Holder {
        int count;
        Sub() { super(new Inner(1), "s"); }
        public int count() { return count; }
        public void bump() { count++; }
    }

    public static final Holder HOLDER = new Holder(new Inner(1), "h");
    public static final Box BOX = new Box(new ArrayList<>(List.of("a")));
    public static final Holder SUB = new Sub();

    // R2: an enum's values()
    public enum Color { RED, GREEN }

    public enum Counter {
        ONE;
        int n;
        public int n() { return n; }
        public void bump() { n++; }
    }

    // R3: JDK immutable collections and Optional, by their elements
    public static final List<String> NAMES = List.of("a", "b");
    public static final List<StringBuilder> BUILDERS = List.of(new StringBuilder("x"));
    public static final Optional<String> OPT = Optional.of("x");
    public static final Optional<AtomicInteger> OPT_MUT = Optional.of(new AtomicInteger());

    // R1 on lambdas: non-capturing, and capturing a mutable object
    public static final Function<String, Integer> LEN = String::length;
    private static final AtomicInteger CAPTURED = new AtomicInteger();
    public static final IntSupplier COUNTER = () -> CAPTURED.get();
    public static final IntSupplier BUMPED = makeBumped(new AtomicInteger());

    static IntSupplier makeBumped(AtomicInteger a) {
        return a::incrementAndGet;
    }

    // a JDK object with only final fields whose state lives elsewhere: stays mutable
    public static final ThreadLocal<String> TL = new ThreadLocal<>();
}
