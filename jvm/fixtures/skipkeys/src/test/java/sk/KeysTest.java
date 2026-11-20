package sk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.junit.jupiter.api.Test;

/** One test per skip-key input; each reads exactly one kind of input. */
class KeysTest {
    static Path root() {
        return Paths.get(System.getProperty("sk.root"));
    }

    @Test
    void code() {
        assertTrue(Calc.add(2, 2) > 0);
    }

    @Test
    void fileRead() throws Exception {
        assertTrue(Files.readAllLines(root().resolve("data/input.txt")).size() > 0);
    }

    @Test
    void fileProbe() {
        Files.exists(root().resolve("data/flag"));
    }

    @Test
    void dirList() throws Exception {
        assertTrue(root().resolve("data/dir").toFile().list().length > 0);
    }

    @Test
    void resource() throws Exception {
        try (InputStream in = KeysTest.class.getResourceAsStream("/res.txt")) {
            assertNotNull(in);
        }
    }

    @Test
    void env() {
        System.getenv("SK_MODE");
    }

    @Test
    void prop() {
        assertNotNull(System.getProperty("sk.prop"));
    }

    @Test
    void unchanged() {
        assertEquals("other", Other.name());
    }
}
