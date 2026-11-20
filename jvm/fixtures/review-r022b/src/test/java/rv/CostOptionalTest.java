package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Cost probe: reads only state that cannot change after initialisation. */
class CostOptionalTest {
    @Test
    void read() {
        assertEquals("x", Cost.OPT.get());
    }
}
