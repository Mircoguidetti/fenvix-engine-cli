package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Probe: reads only state that cannot change (R1). Must not be mut. */
class ProbeDeepFinalTest {
    @Test
    void read() {
        assertEquals(1, State.HOLDER.x());
    }
}
