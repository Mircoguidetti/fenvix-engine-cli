package dev.fenvix.rt;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.management.ManagementFactory;

/** Java 8 compatibility helpers (the runtime and agent are compiled for Java 8). */
public final class Compat {
    private Compat() {}

    public static byte[] readAll(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[1 << 14];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        return out.toByteArray();
    }

    private static volatile String pid;

    public static String pid() {
        String p = pid;
        if (p == null) {
            String n = ManagementFactory.getRuntimeMXBean().getName();
            int at = n.indexOf('@');
            p = at > 0 ? n.substring(0, at) : n;
            pid = p;
        }
        return p;
    }

    private static volatile ClassLoader platform;
    private static volatile boolean platformLooked;

    /** The platform (9+) or extension (8) class loader. */
    public static ClassLoader platformLoader() {
        if (!platformLooked) {
            try {
                platform = (ClassLoader) ClassLoader.class.getMethod("getPlatformClassLoader").invoke(null);
            } catch (Exception e) {
                ClassLoader l = ClassLoader.getSystemClassLoader();
                while (l != null && l.getParent() != null) l = l.getParent();
                platform = l; // Java 8: the extension class loader
            }
            platformLooked = true;
        }
        return platform;
    }

    public static int javaMajor() {
        String v = System.getProperty("java.specification.version", "1.8");
        return v.startsWith("1.") ? Integer.parseInt(v.substring(2)) : Integer.parseInt(v.split("\\.")[0]);
    }
}
