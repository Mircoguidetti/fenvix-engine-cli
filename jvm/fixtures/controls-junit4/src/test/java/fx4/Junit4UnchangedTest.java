package fx4;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class Junit4UnchangedTest {
    @Test
    public void a() {
        assertEquals(4, 2 + 2);
    }

    @Test
    public void b() {
        assertEquals("ab", "a" + "b");
    }

    @Test
    public void c() {
        assertEquals(1, Integer.signum(5));
    }

    @Test
    public void d() {
        assertEquals(9, 3 * 3);
    }
}
