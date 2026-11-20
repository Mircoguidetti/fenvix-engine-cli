package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.File;
import org.junit.jupiter.api.Test;

/** Native code reads a repository file. */
class NativeTest {
    @Test
    void nativeReadsFile() {
        String root = System.getProperty("rv.root");
        System.load(new File(root, "build/native/librvnative.so").getAbsolutePath());
        assertEquals("one", NativeReader.firstLine(root + "/data/native.txt"));
    }
}
