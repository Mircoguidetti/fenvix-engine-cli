package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

/** A child process reads a file of the repository. */
class ProcTest {
    @Test
    void childReadsFile() throws Exception {
        String root = System.getProperty("rv.root");
        Process p = new ProcessBuilder("cat", root + "/data/proc.txt").start();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (InputStream in = p.getInputStream()) {
            byte[] buf = new byte[256];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        }
        p.waitFor();
        assertEquals("one", new String(out.toByteArray(), StandardCharsets.UTF_8).trim());
    }
}
