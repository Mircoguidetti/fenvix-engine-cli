package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Probe: reads only state that cannot change (R3). Must not be mut. */
class ProbeListOfTest {
    @Test
    void read() {
        assertEquals(2, State.NAMES.size());
    }
}
