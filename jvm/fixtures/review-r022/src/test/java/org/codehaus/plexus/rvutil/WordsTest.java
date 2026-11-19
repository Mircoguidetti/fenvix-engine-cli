package org.codehaus.plexus.rvutil;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class WordsTest {
    @Test
    void join() {
        assertEquals("a-b", Words.join("a", "b"));
    }
}
