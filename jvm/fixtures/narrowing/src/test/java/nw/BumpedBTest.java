package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario Bumped: unchanged; must run again when the writer changes the state. */
class BumpedBTest {
    @Test
    void read() {
        assertEquals(1, State.BUMPED.getAsInt());
    }
}
