package fx4;

import static org.junit.Assert.assertEquals;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

final class Same {
    private Same() {}

    static void check(String name, Object value) throws Exception {
        Path dir = Paths.get(System.getProperty("fx.state", "build/fx-state"));
        Files.createDirectories(dir);
        Path f = dir.resolve(name);
        String v = String.valueOf(value);
        if (Files.exists(f)) assertEquals(name + " differs from the previous run", new String(Files.readAllBytes(f), StandardCharsets.UTF_8), v);
        else Files.write(f, v.getBytes(StandardCharsets.UTF_8));
    }
}
