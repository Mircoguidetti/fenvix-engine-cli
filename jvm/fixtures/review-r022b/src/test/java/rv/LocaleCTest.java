package rv;

import org.junit.jupiter.api.Test;

/**
 * Runs after LocaleBTest and restores the default locale the JVM started with (a cleanup test, or
 * any @AfterAll that resets it): the end-of-JVM locale in B equals A's, so the runtime record does
 * not differ.
 */
class LocaleCTest {
    @Test
    void restore() {
        java.util.Locale.setDefault(java.util.Locale.US);
    }
}
