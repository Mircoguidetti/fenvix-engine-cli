package sk;

import static org.junit.jupiter.api.Assertions.assertNotNull;

import org.junit.jupiter.api.Test;

/** Reads the static field written by StaticATest: depends on it. */
class StaticBTest {
    @Test
    void reader() {
        assertNotNull(Registry.value);
    }
}
