package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Probe: reads only state that cannot change (R1, lambda). Must not be mut. */
class ProbeLambdaTest {
    @Test
    void read() {
        assertEquals(3, State.LEN.apply("abc"));
    }
}
