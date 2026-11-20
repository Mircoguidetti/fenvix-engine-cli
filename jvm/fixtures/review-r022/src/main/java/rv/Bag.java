package rv;

import java.util.ArrayList;
import java.util.List;

/** Shared mutable state reached through a static field that is never reassigned. */
public final class Bag {
    public static final List<String> ITEMS = new ArrayList<>();

    private Bag() {}
}
