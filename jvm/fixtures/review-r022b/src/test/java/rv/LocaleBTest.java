package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario locale-default: unchanged in every scenario. */
class LocaleBTest {
    @Test
    void read() throws Exception {
        assertEquals("1.5", String.format("%.1f", 1.5));
    }
}
