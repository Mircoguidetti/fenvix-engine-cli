package rv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvFileSource;

/** Arguments read from a classpath CSV by JUnit (infrastructure). */
class CsvTest {
    @ParameterizedTest
    @CsvFileSource(resources = "/sums.csv")
    void sum(int a, int b, int c) {
        assertEquals(c, a + b);
    }
}
