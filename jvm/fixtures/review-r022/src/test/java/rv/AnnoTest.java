package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Reads an annotation default reflectively: no code of Cfg or Service runs. */
class AnnoTest {
    @Test
    void retries() {
        assertEquals(3, Service.class.getAnnotation(Cfg.class).retries());
    }
}
