package rv;

import java.util.ArrayList;
import java.util.List;

/**
 * A registry whose static initialiser calls size() before ITEMS is assigned (a common init-order
 * slip: logging or validation in a static block above the field). The GETSTATIC in size() first
 * executes during <clinit> and sees null.
 */
public final class Reg {
    static {
        if (size() > 0) throw new IllegalStateException();
    }

    public static final List<String> ITEMS = new ArrayList<>();

    private Reg() {}

    public static int size() {
        return ITEMS == null ? 0 : ITEMS.size();
    }
}
