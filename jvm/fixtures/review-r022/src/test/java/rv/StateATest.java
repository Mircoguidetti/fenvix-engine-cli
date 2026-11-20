package rv;

import org.junit.jupiter.api.Test;

/** Assigns Shared.value (PUTSTATIC): StateCTest records a dependency on this test. */
class StateATest {
    @Test
    void write() {
        Shared.value = 1;
    }
}
