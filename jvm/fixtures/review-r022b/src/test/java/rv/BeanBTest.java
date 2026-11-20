package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario introspector-cache: unchanged in every scenario. */
class BeanBTest {
    @Test
    void read() throws Exception {
        assertEquals(3, java.beans.Introspector.getBeanInfo(Bean.class).getPropertyDescriptors().length);
    }
}
