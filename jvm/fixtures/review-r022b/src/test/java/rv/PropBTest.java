package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario property-via-jdk: unchanged in every scenario. */
class PropBTest {
    @Test
    void read() throws Exception {
        assertFalse(Boolean.getBoolean("rv.flag"));
    }
}
