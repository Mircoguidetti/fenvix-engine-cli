package fx;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;
import java.util.TreeMap;
import org.junit.jupiter.api.Test;

/** Deterministic tests: --det must not change their outcome. */
class UnchangedTest {
    @Test
    void arithmetic() {
        assertEquals(42, 6 * 7);
    }

    @Test
    void sortedCollections() {
        TreeMap<String, Integer> m = new TreeMap<>();
        m.put("b", 2);
        m.put("a", 1);
        assertEquals(java.util.Arrays.asList("a", "b"), new java.util.ArrayList<>(m.keySet()));
    }

    @Test
    void stringFormat() {
        assertEquals("x=007", String.format("x=%03d", 7));
    }
}
