package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Probe: reads only state that cannot change (R2). Must not be mut. */
class ProbeEnumValuesTest {
    @Test
    void read() {
        assertEquals(2, State.Color.values().length);
    }
}
