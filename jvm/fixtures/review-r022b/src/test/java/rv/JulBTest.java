package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario jul-root-level: unchanged in every scenario. */
class JulBTest {
    @Test
    void read() throws Exception {
        assertNotEquals(Integer.MAX_VALUE, java.util.logging.Logger.getLogger("").getLevel().intValue());
    }
}
