package dev.fenvix.agent;

import java.io.File;
import java.io.InputStream;
import java.lang.instrument.Instrumentation;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.jar.JarFile;

/**
 * {@code -javaagent:fenvix-agent.jar[=key=value,...]}: the entry point of the JVM
 * shell inside a test JVM.
 *
 * <p>Agent options become {@code fenvix.*} system properties ({@code det},
 * {@code deps}, {@code seed}, {@code out}, {@code root}, {@code module},
 * {@code disable}, ...); system properties already set win. The agent then
 * puts the runtime (fenvix-rt.jar, embedded) on the bootstrap class path, loads
 * the Rust core (JNI), opens a few java.base packages to the runtime, and
 * installs the transformers. This class touches no runtime class itself: they
 * must be loaded from the bootstrap path, after it is extended.
 */
public final class Agent {
    private Agent() {}

    public static void premain(String args, Instrumentation inst) {
        try {
            start(args, inst);
        } catch (Throwable t) {
            System.err.println("fenvix: agent failed to start: " + t);
            t.printStackTrace();
            if (Boolean.getBoolean("fenvix.strict")) throw new RuntimeException(t);
        }
    }

    public static void agentmain(String args, Instrumentation inst) {
        premain(args, inst);
    }

    static void start(String args, Instrumentation inst) throws Exception {
        if (args != null) {
            for (String kv : args.split(",")) {
                if (kv.isEmpty()) continue;
                int eq = kv.indexOf('=');
                String k = "fenvix." + (eq < 0 ? kv : kv.substring(0, eq));
                String v = eq < 0 ? "1" : kv.substring(eq + 1);
                if (System.getProperty(k) == null) System.setProperty(k, v);
            }
        }
        Path dir = extract();
        inst.appendToBootstrapClassLoaderSearch(new JarFile(dir.resolve("fenvix-rt.jar").toFile()));
        System.setProperty("fenvix.native", dir.resolve("libfenvix_jvm.so").toString());
        Installer.install(inst, dir);
    }

    static byte[] readAll(InputStream in) throws java.io.IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[1 << 14];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        return out.toByteArray();
    }

    /** Self location of the agent jar. */
    static File self() throws Exception {
        return new File(Agent.class.getProtectionDomain().getCodeSource().getLocation().toURI());
    }

    /**
     * Extract the embedded runtime jar and native library into a directory named
     * after their digest (shared by every JVM of a run, written atomically).
     */
    static Path extract() throws Exception {
        return extract(new String[] {"fenvix-rt.jar", "libfenvix_jvm.so"});
    }

    /** Every embedded asset (CLI: also the init script and the Maven extension). */
    public static Path extractAll() throws Exception {
        return extract(new String[] {"fenvix-rt.jar", "libfenvix_jvm.so", "fenvix.init.gradle", "fenvix-maven-ext.jar"});
    }

    static Path extract(String[] names) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[][] data = new byte[names.length][];
        for (int i = 0; i < names.length; i++) {
            try (InputStream in = Agent.class.getResourceAsStream("/fenvix/" + names[i])) {
                if (in == null) throw new IllegalStateException("fenvix agent jar lacks /fenvix/" + names[i]);
                data[i] = readAll(in);
            }
            md.update(data[i]);
        }
        StringBuilder h = new StringBuilder();
        for (byte b : md.digest()) h.append(String.format("%02x", b));
        String base = System.getProperty("fenvix.cache", System.getProperty("java.io.tmpdir") + "/fenvix-jvm");
        Path dir = Paths.get(base, h.substring(0, 16));
        Files.createDirectories(dir);
        for (int i = 0; i < names.length; i++) {
            Path p = dir.resolve(names[i]);
            if (Files.exists(p) && Files.size(p) == data[i].length) continue;
            Path tmp = Files.createTempFile(dir, names[i], ".part");
            Files.write(tmp, data[i]);
            Files.move(tmp, p, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        }
        return dir;
    }
}
