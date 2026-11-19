package rj;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class PlainJunit4Test {
    @Test
    public void a() {
        assertEquals(4, 2 + 2);
    }

    @Test
    public void b() {
        assertEquals("ab", "a" + "b");
    }
}
