package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario Reg: unchanged; must run again when the writer changes the state. */
class RegBTest {
    @Test
    void read() {
        assertEquals(0, Reg.size());
    }
}
