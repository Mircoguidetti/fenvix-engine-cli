package fx;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** "Same value as in the previous run": the first run records, later runs compare. */
final class Same {
    private Same() {}

    static void check(String name, Object value) throws Exception {
        Path dir = Paths.get(System.getProperty("fx.state", "build/fx-state"));
        Files.createDirectories(dir);
        Path f = dir.resolve(name);
        String v = String.valueOf(value);
        if (Files.exists(f)) {
            assertEquals(new String(Files.readAllBytes(f), StandardCharsets.UTF_8), v, name + " differs from the previous run");
        } else {
            Files.write(f, v.getBytes(StandardCharsets.UTF_8));
        }
    }
}
