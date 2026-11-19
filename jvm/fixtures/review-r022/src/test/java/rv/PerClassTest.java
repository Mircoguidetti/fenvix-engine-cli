package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.TestMethodOrder;

/** JUnit lifecycle PER_CLASS: the instance field is shared by the two methods. */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@TestMethodOrder(MethodOrderer.MethodName.class)
class PerClassTest {
    final List<String> list = new ArrayList<>();

    @Test
    void a_fill() {
        Filler.fill(list);
    }

    @Test
    void b_count() {
        assertEquals(1, list.size());
    }
}
