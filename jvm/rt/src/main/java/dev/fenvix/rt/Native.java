package dev.fenvix.rt;

/**
 * JNI entry points of the Rust core (crates/fenvix-jvm over detpy-core).
 *
 * <p>This class lives on the bootstrap class path (the agent appends the rt jar
 * there), so the native library is bound to the bootstrap loader and every
 * class loader of the test JVM sees one recorder.
 */
public final class Native {
    private Native() {}

    private static volatile boolean loaded;

    /** Load the library from {@code fenvix.native} (set by the agent). */
    public static synchronized void load(String path) {
        if (loaded) return;
        System.load(path);
        loaded = true;
    }

    public static boolean isLoaded() {
        return loaded;
    }

    public static native int encodingVersion();

    public static native int traceVersion();

    public static native long recorderNew(int maxEvents, int checkpointEvery);

    public static native void recorderFree(long h);

    public static native void recorderOpen(long h, String path, String metaJson, String[] order);

    public static native void recorderBegin(long h, String nodeid, int index);

    public static native int recorderRecordPacked(long h, String packed);

    public static native String recorderEnd(long h, String outcome);

    public static native String recorderClose(long h);

    public static native String verify(String[] paths);

    public static native String verifyText(String[] paths, boolean showStable);

    public static native long deriveSeed(long base, String key);

    public static native int[] shuffleIndices(int n, long seed, String key);

    public static native String orderDigest(String[] ids);

    public static native String digest(byte[] data);

    public static native String digestFile(String path);

    public static native String mergeTraces(String[] parts, String out, String metaJson, String[] order);
}
