package rv;

import static org.junit.jupiter.api.Assertions.assertFalse;

import org.junit.jupiter.api.Test;

/** Order-dependent victim: passes alone and with the tests of the base commit, fails after a polluter. */
class VictimTest {
    @Test
    void flagIsOff() {
        assertFalse(Flag.on);
    }
}
