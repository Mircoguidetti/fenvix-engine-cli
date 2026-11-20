package rv;

import java.util.ServiceLoader;

/** Counts the Greeter providers on the class path. */
public final class Greeters {
    private Greeters() {}

    public static int count() {
        int n = 0;
        for (Greeter g : ServiceLoader.load(Greeter.class)) {
            n++;
        }
        return n;
    }
}
