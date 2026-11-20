package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Cost probe: reads only state that cannot change after initialisation. */
class CostSwitchTest {
    @Test
    void read() {
        assertEquals("g", Cost.name(Cost.Color.GREEN));
    }
}
