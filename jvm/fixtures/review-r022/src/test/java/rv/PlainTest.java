package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Reads none of the changed inputs: reused in every scenario that is not global. */
class PlainTest {
    @Test
    void unchanged() {
        assertEquals(4, 2 + 2);
    }
}
