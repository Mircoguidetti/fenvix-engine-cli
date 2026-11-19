package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Reads Shared.value; scenario new-writer-test adds StateBTest, which runs between A and C. */
class StateCTest {
    @Test
    void read() {
        assertEquals(1, Shared.value);
    }
}
