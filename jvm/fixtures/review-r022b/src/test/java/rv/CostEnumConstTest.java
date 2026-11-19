package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Cost probe: reads only state that cannot change after initialisation. */
class CostEnumConstTest {
    @Test
    void read() {
        assertNotNull(Cost.Color.RED);
    }
}
