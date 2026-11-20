package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario Box: unchanged; must run again when the writer changes the state. */
class BoxBTest {
    @Test
    void read() {
        assertEquals(1, State.BOX.items().size());
    }
}
