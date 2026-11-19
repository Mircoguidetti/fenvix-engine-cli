package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Cost probe: reads only state that cannot change after initialisation. */
class CostListOfTest {
    @Test
    void read() {
        assertEquals(2, Cost.NAMES.size());
    }
}
