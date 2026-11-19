package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Writer of scenario resource-bundle-cache: in the base run it leaves nothing behind; the scenario adds the effect. */
class MsgATest {
    @Test
    void write() throws Exception {
        assertNotNull(java.util.ResourceBundle.getBundle("rvmsg").getString("greeting"));
        /*EFFECT*/
    }
}
