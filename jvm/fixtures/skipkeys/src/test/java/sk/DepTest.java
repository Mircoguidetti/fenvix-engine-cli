package sk;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.apache.commons.lang3.StringUtils;
import org.junit.jupiter.api.Test;

/** Uses a class from a dependency jar. */
class DepTest {
    @Test
    void library() {
        assertEquals("abc", StringUtils.trim(" abc "));
    }
}
