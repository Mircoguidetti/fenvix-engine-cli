package rv;

import java.util.List;

/** Mutates a list it is given (scenario heap-state changes this class). */
public final class Filler {
    private Filler() {}

    public static void fill(List<String> l) {
        l.add("a");
    }
}
