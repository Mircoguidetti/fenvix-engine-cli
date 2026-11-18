package fx;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/**
 * Control "order": the project's baseline is MethodOrderer$Random
 * (junit-platform.properties) with a seed that runs polluter() first; under
 * --det seed 0 the order is fixed (Jupiter's default order: victim() first).
 */
class OrderControlTest {
    static int shared;

    @Test
    void victim() {
        assertEquals(0, shared, "polluter ran first");
    }

    @Test
    void polluter() {
        shared = 1;
    }
}
