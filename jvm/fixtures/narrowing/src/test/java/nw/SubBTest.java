package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario Sub: unchanged; must run again when the writer changes the state. */
class SubBTest {
    @Test
    void read() {
        assertEquals(0, ((State.Sub) State.SUB).count());
    }
}
