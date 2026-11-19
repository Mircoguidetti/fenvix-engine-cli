package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario Counter: unchanged; must run again when the writer changes the state. */
class CounterBTest {
    @Test
    void read() {
        assertEquals(0, State.Counter.values()[0].n());
    }
}
