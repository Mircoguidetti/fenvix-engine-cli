package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Writer of scenario introspector-cache: in the base run it leaves nothing behind; the scenario adds the effect. */
class BeanATest {
    @Test
    void write() throws Exception {
        assertNotNull(java.beans.Introspector.getBeanInfo(Bean.class));
        /*EFFECT*/
    }
}
