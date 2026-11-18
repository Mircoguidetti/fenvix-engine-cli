package sk;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.junit.jupiter.api.Test;

/** Tests that are never reused: external network attempt, a file written and read back. */
class NeverTest {
    @Test
    void network() {
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress(InetAddress.getByAddress(new byte[] {1, 1, 1, 1}), 443), 500);
        } catch (IOException expected) {
            // blocked under --det, or no route: either way the test touched the network
        }
    }

    @Test
    void writesItsInput() throws Exception {
        Path p = Paths.get(System.getProperty("sk.root"), "build", "sk-out.txt");
        Files.createDirectories(p.getParent());
        Files.write(p, "x".getBytes());
        assertEquals("x", new String(Files.readAllBytes(p)));
    }
}
