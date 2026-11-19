package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario clinit-null-read: unchanged in every scenario. */
class RegBTest {
    @Test
    void read() throws Exception {
        assertEquals(0, Reg.size());
    }
}
