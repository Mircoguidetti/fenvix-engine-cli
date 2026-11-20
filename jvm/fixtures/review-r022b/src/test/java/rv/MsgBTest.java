package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario resource-bundle-cache: unchanged in every scenario. */
class MsgBTest {
    @Test
    void read() throws Exception {
        assertEquals("hello", java.util.ResourceBundle.getBundle("rvmsg").getString("greeting"));
    }
}
