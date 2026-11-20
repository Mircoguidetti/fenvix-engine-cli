package nw;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario OptMut: unchanged; must run again when the writer changes the state. */
class OptMutBTest {
    @Test
    void read() {
        assertEquals(0, State.OPT_MUT.get().get());
    }
}
