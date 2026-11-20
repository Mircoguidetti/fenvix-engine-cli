package l1

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import java.util.Collections

/** Kotlin coroutines under Level 0, measured only. */
class CoroutineTest {
    @Test
    fun delaysInRunBlocking() = runBlocking {
        val order = Collections.synchronizedList(mutableListOf<Int>())
        launch { delay(200); order.add(2) }
        launch { delay(100); order.add(1) }
        delay(300)
        assertEquals(listOf(1, 2), order)
    }

    @Test
    fun virtualTimeOfRunTest() = runTest {
        delay(10_000)
        assertEquals(10_000L, testScheduler.currentTime)
    }

    @Test
    fun withTimeoutHolds() = runBlocking {
        withTimeout(2_000) { delay(50) }
    }

    @Test
    fun defaultDispatcherRace() = runBlocking {
        val seen = Collections.synchronizedList(mutableListOf<Int>())
        withContext(Dispatchers.Default) {
            (0 until 8).map { i -> async { var x = 0L; repeat(100_000 * (8 - i)) { x += it }; seen.add(i); x } }.awaitAll()
        }
        assertEquals((0 until 8).toList(), seen)
    }
}
