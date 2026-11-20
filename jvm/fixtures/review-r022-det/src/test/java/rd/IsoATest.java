package rd;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Switches the process-wide mode; relies on its own JVM (reuseForks=false / forkEvery=1). */
class IsoATest {
    @Test
    void strict() {
        Mode.enable("strict");
        assertEquals("strict", Mode.current());
    }
}
