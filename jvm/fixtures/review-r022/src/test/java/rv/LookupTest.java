package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Lookups that find nothing: an optional resource, a class by computed name, ServiceLoader providers. */
class LookupTest {
    @Test
    void resourceAbsent() throws Exception {
        assertEquals("default", Settings.mode());
    }

    @Test
    void classAbsent() {
        assertEquals("default", Plugins.active());
    }

    @Test
    void noProvider() {
        assertEquals(0, Greeters.count());
    }
}
