package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Probe: reads only state that cannot change (R3). Must not be mut. */
class ProbeOptionalTest {
    @Test
    void read() {
        assertEquals("x", State.OPT.get());
    }
}
