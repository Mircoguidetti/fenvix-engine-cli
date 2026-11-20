package fx;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

/** File timestamps and the clock agree (under --det the clock is virtual: timestamps follow it). */
class FileTimeTest {
    @Test
    void newFileIsRecent() throws Exception {
        File f = File.createTempFile("fx-time", ".txt");
        long age = System.currentTimeMillis() - f.lastModified();
        assertTrue(Math.abs(age) < 60_000, "age " + age);
        Path p = f.toPath();
        long age2 = System.currentTimeMillis() - Files.getLastModifiedTime(p).toMillis();
        assertTrue(Math.abs(age2) < 60_000, "nio age " + age2);
        f.delete();
    }

    @Test
    void setLastModifiedRoundTrips() throws Exception {
        File f = File.createTempFile("fx-time", ".txt");
        long oneDayAgo = System.currentTimeMillis() - 86_400_000L;
        assertTrue(f.setLastModified(oneDayAgo));
        assertTrue(Math.abs(f.lastModified() - oneDayAgo) < 2_000, "round trip");
        f.delete();
    }
}
