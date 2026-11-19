package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Reads the list HeapATest filled (classes run in name order under --det). */
class HeapBTest {
    @Test
    void count() {
        assertEquals(1, Bag.ITEMS.size());
    }
}
