package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;

/**
 * Reads an inherited interface constant by simple name (javac emits GETSTATIC LimitsTest.MAX).
 * Limits' static initialiser runs once, inside the first method.
 */
@TestMethodOrder(MethodOrderer.MethodName.class)
class LimitsTest implements Limits {
    @Test
    void a_first() {
        assertEquals(3, MAX.intValue());
    }

    @Test
    void b_second() {
        assertEquals(3, MAX.intValue());
    }
}
