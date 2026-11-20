package rv;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

/** Reader of scenario context-class-loader: unchanged in every scenario. */
class TcclBTest {
    @Test
    void read() throws Exception {
        assertNotNull(Thread.currentThread().getContextClassLoader().getResource("rv-tccl.txt"));
    }
}
