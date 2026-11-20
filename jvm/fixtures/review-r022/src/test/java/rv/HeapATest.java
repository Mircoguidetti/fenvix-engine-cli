package rv;

import org.junit.jupiter.api.Test;

/** Mutates Bag.ITEMS through Filler (no static field is assigned: GETSTATIC only). */
class HeapATest {
    @Test
    void fill() {
        Filler.fill(Bag.ITEMS);
    }
}
