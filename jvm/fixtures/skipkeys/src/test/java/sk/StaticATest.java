package sk;

import org.junit.jupiter.api.Test;

/** Writes a static field that StaticBTest reads (runs first: classes in name order under --det). */
class StaticATest {
    @Test
    void writer() {
        Registry.value = "written by A";
    }
}
