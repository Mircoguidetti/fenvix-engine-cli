package nw;

import java.util.ArrayList;
import java.util.List;

/** A final static read as null inside its class's own initialiser (one read site), then filled by tests. */
public final class Reg {
    static {
        if (size() > 0) throw new IllegalStateException();
    }

    public static final List<String> ITEMS = new ArrayList<>();

    private Reg() {}

    public static int size() {
        List<String> l = ITEMS;
        return l == null ? 0 : l.size();
    }
}
