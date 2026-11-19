package nw;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Reads nothing that changes: reused in every scenario. */
class PlainTest {
    @Test
    void unchanged() {
        assertEquals(4, 2 + 2);
    }
}
