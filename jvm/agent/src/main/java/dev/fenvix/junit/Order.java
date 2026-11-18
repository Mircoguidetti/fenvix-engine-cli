package dev.fenvix.junit;

import dev.fenvix.rt.Native;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Seeded ranks over a sorted list of names (Rust core shuffle). */
final class Order {
    private Order() {}

    static long seed() {
        try {
            return Long.parseLong(System.getProperty("fenvix.seed", "0"));
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    static Map<String, Integer> rank(List<String> sorted, long seed, String key) {
        Map<String, Integer> r = new HashMap<>();
        if (seed == 0) {
            for (int i = 0; i < sorted.size(); i++) r.putIfAbsent(sorted.get(i), i);
            return r;
        }
        int[] perm = Native.shuffleIndices(sorted.size(), seed, key);
        for (int pos = 0; pos < perm.length; pos++) r.putIfAbsent(sorted.get(perm[pos]), pos);
        return r;
    }
}
