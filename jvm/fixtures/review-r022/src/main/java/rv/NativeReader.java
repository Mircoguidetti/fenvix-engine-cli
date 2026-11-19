package rv;

/** JNI reader (src/native/rvnative.c, built by jvm/test/run_review_r022.py into build/native). */
public final class NativeReader {
    private NativeReader() {}

    public static native String firstLine(String path);
}
