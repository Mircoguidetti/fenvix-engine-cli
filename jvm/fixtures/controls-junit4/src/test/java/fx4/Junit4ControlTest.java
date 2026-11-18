package fx4;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.net.ConnectException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Random;
import java.util.UUID;
import org.junit.Test;

/** The Level 0 controls through the JUnit 4 runner (Surefire junit4 provider, Gradle useJUnit()). */
public class Junit4ControlTest {
    @Test
    public void newRandom() throws Exception {
        Same.check("j4-newRandom", new Random().nextLong());
    }

    @Test
    public void uuid() throws Exception {
        Same.check("j4-uuid", UUID.randomUUID());
    }

    @Test
    public void currentTimeMillis() throws Exception {
        Same.check("j4-currentTimeMillis", System.currentTimeMillis());
    }

    @Test(timeout = 1500)
    public void sleepIsVirtual() throws Exception {
        Thread.sleep(3_000);
    }

    @Test
    public void listingIsSorted() throws Exception {
        File d = Files.createTempDirectory("fx4").toFile();
        List<String> names = new ArrayList<>();
        for (int i = 0; i < 200; i++) {
            String n = Integer.toHexString((i * 7919) % 4093) + "-" + i;
            new File(d, n).createNewFile();
            names.add(n);
        }
        names.sort(null);
        assertEquals(names, Arrays.asList(d.list()));
    }

    @Test
    public void externalConnectIsRefused() throws Exception {
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress(InetAddress.getByAddress(new byte[] {93, (byte) 184, (byte) 215, 14}), 80), 3000);
            throw new AssertionError("connected");
        } catch (ConnectException e) {
            assertTrue(e.getMessage(), e.getMessage().contains("fenvix"));
        }
    }
}
