package rd;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Expects a fresh JVM, as the build configures. */
class IsoBTest {
    @Test
    void lenient() {
        Mode.enable("lenient");
        assertEquals("lenient", Mode.current());
    }
}
