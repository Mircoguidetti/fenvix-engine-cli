package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario Tl: unchanged; must run again when the writer changes the state. */
class TlBTest {
    @Test
    void read() {
        assertNull(State.TL.get());
    }
}
