package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario Builders: unchanged; must run again when the writer changes the state. */
class BuildersBTest {
    @Test
    void read() {
        assertEquals("x", State.BUILDERS.get(0).toString());
    }
}
