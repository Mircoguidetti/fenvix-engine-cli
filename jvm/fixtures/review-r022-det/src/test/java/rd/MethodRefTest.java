package rd;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Random;
import java.util.function.LongSupplier;
import java.util.function.Supplier;
import org.junit.jupiter.api.Test;

/**
 * Clock and randomness reached through method references (invokedynamic, no INVOKESTATIC call site):
 * an injectable clock {@code LongSupplier clock = System::currentTimeMillis} is a common pattern.
 * Only meaningful under --det: skipped when the direct clock is the real one.
 */
class MethodRefTest {
    static boolean det() {
        return Instant.ofEpochMilli(System.currentTimeMillis()).atZone(ZoneOffset.UTC).getYear() == 2025;
    }

    @Test
    void clockByMethodReference() {
        assumeTrue(det(), "--det only");
        LongSupplier clock = System::currentTimeMillis;
        Supplier<Instant> now = Instant::now;
        assertEquals(2025, Instant.ofEpochMilli(clock.getAsLong()).atZone(ZoneOffset.UTC).getYear(), "System::currentTimeMillis");
        assertEquals(2025, now.get().atZone(ZoneOffset.UTC).getYear(), "Instant::now");
    }

    @Test
    void randomByMethodReference() throws Exception {
        assumeTrue(det(), "--det only");
        Supplier<Random> factory = Random::new;
        long v = factory.get().nextLong();
        // the runner compares this value across two --det runs
        File out = new File(System.getProperty("rd.out"), "random-method-ref.txt");
        out.getParentFile().mkdirs();
        try (FileOutputStream o = new FileOutputStream(out)) {
            o.write(Long.toString(v).getBytes(StandardCharsets.UTF_8));
        }
    }
}
