package fx;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.File;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/** Control "fs": directory listings come in name order under --det. */
class FsControlTest {
    static Path dir;
    static List<String> sorted = new ArrayList<>();

    @BeforeAll
    static void makeFiles() throws Exception {
        dir = Files.createTempDirectory("fx-fs");
        for (int i = 0; i < 300; i++) {
            String n = Integer.toHexString((i * 7919) % 4093) + "-" + i + ".txt";
            Files.write(dir.resolve(n), new byte[] {1});
            sorted.add(n);
        }
        sorted.sort(null);
    }

    @Test
    void fileList() {
        assertEquals(sorted, Arrays.asList(dir.toFile().list()));
    }

    @Test
    void fileListFiles() {
        List<String> names = new ArrayList<>();
        for (File f : dir.toFile().listFiles()) names.add(f.getName());
        assertEquals(sorted, names);
    }

    @Test
    void filesList() throws Exception {
        try (Stream<Path> s = Files.list(dir)) {
            assertEquals(sorted, s.map(p -> p.getFileName().toString()).collect(Collectors.toList()));
        }
    }

    @Test
    void directoryStream() throws Exception {
        List<String> names = new ArrayList<>();
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(dir)) {
            for (Path p : ds) names.add(p.getFileName().toString());
        }
        assertEquals(sorted, names);
    }

    @Test
    void filesWalk() throws Exception {
        try (Stream<Path> s = Files.walk(dir, 1)) {
            List<String> names = s.skip(1).map(p -> p.getFileName().toString()).collect(Collectors.toList());
            assertEquals(sorted, names);
        }
    }
}
