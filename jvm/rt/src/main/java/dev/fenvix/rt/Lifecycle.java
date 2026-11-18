package dev.fenvix.rt;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.InputStream;
import java.lang.management.ManagementFactory;
import java.net.URL;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.TreeSet;

/** Trace header, shutdown, runtime identity and configuration of the test JVM. */
public final class Lifecycle {
    private Lifecycle() {}

    private static volatile boolean finished;

    public static void installShutdownHook() {
        Runtime.getRuntime().addShutdownHook(new Thread(Lifecycle::finish, "fenvix-shutdown"));
    }

    /** Close the trace and write the deps footer (idempotent). */
    public static synchronized void finish() {
        if (finished) return;
        finished = true;
        try {
            Det.closeTrace();
        } catch (Throwable t) {
            System.err.println("fenvix: closing the trace failed: " + t);
        }
        if (Det.DEPS) {
            try {
                Deps.finish(runtime(), config());
            } catch (Throwable t) {
                System.err.println("fenvix: writing deps failed: " + t);
            }
        }
    }

    /** JSON object for the trace header meta (shared vocabulary). */
    public static String metaJson(String runner, String runnerVersion, String isolation) {
        StringBuilder sb = new StringBuilder("{");
        kv(sb, "runtime", "jvm").append(',');
        kv(sb, "runtime_version", System.getProperty("java.runtime.version", System.getProperty("java.version"))).append(',');
        kv(sb, "jvm_vendor", System.getProperty("java.vendor")).append(',');
        kv(sb, "runner", runner).append(',');
        kv(sb, "runner_version", runnerVersion).append(',');
        kv(sb, "tool", System.getProperty("fenvix.tool", "")).append(',');
        kv(sb, "module", Det.MODULE).append(',');
        sb.append("\"seed\":").append(Det.SEED).append(',');
        sb.append("\"controls\":");
        List<String> c = new ArrayList<>();
        for (String s : Det.controls().split(",")) if (!s.isEmpty()) c.add(s);
        Json.strs(sb, c);
        sb.append(',');
        kv(sb, "jdk_randoms", JdkRandoms.reachable()).append(',');
        kv(sb, "jdk_hooks", System.getProperty("fenvix.meta.jdkhooks", "")).append(',');
        kv(sb, "isolation", isolation).append(',');
        sb.append("\"serial\":true,");
        kv(sb, "identity_hash", identityHashMode());
        sb.append('}');
        return sb.toString();
    }

    static StringBuilder kv(StringBuilder sb, String k, String v) {
        Json.str(sb, k);
        sb.append(':');
        Json.str(sb, v == null ? "" : v);
        return sb;
    }

    static String identityHashMode() {
        for (String a : ManagementFactory.getRuntimeMXBean().getInputArguments()) {
            if (a.startsWith("-XX:hashCode=")) return a.substring(2);
        }
        return "default";
    }

    /**
     * JVM arguments left out of the runtime identity: the agent, worker ids,
     * debugging, and user system properties (-Dkey=value outside java.*, jdk.*,
     * sun.*, javax.*, com.sun.*): those are part of the key only where a test
     * reads them.
     */
    static boolean volatileArg(String a) {
        if (a.startsWith("-D") && !(a.startsWith("-Djava.") || a.startsWith("-Djdk.") || a.startsWith("-Dsun.")
                || a.startsWith("-Djavax.") || a.startsWith("-Dcom.sun."))) {
            return true;
        }
        return a.startsWith("-javaagent:") || a.startsWith("-Dfenvix.") || a.contains("worker") || a.startsWith("-Xlog")
                || a.startsWith("-agentlib:jdwp") || a.startsWith("-Djava.io.tmpdir") || a.startsWith("-Dbasedir")
                || a.startsWith("-Duser.dir") || a.startsWith("@");
    }

    /** Runtime identity: JDK vendor, version and bytes, JVM flags, native libraries, tool versions. */
    public static Map<String, String> runtime() {
        Map<String, String> m = new TreeMap<>();
        for (String k : new String[] {"java.vendor", "java.runtime.version", "java.vm.name", "java.vm.version", "os.name",
            "os.arch", "file.encoding", "native.encoding", "user.timezone", "user.language", "user.country",
            "line.separator", "java.specification.version"}) {
            m.put("prop:" + k, String.valueOf(System.getProperty(k)));
        }
        m.put("tz", java.util.TimeZone.getDefault().getID());
        m.put("locale", java.util.Locale.getDefault().toString());
        m.put("charset", java.nio.charset.Charset.defaultCharset().name());
        String jh = System.getProperty("java.home");
        File modules = new File(jh, "lib/modules");
        if (modules.exists()) m.put("jdk:modules", Deps.fileState(modules.getAbsolutePath()));
        File rt = new File(jh, "lib/rt.jar");
        if (rt.exists()) m.put("jdk:rt.jar", Deps.fileState(rt.getAbsolutePath()));
        File jvm = new File(jh, "lib/server/libjvm.so");
        if (jvm.exists()) m.put("jdk:libjvm", Deps.fileState(jvm.getAbsolutePath()));
        List<String> args = new ArrayList<>();
        for (String a : ManagementFactory.getRuntimeMXBean().getInputArguments()) if (!volatileArg(a)) args.add(a);
        m.put("jvm:args", String.join(" ", args));
        m.put("tool", System.getProperty("fenvix.tool", ""));
        m.put("tool:plugins", System.getProperty("fenvix.plugins", ""));
        // native libraries mapped into the process, outside the JDK
        TreeSet<String> libs = new TreeSet<>();
        File maps = new File("/proc/self/maps");
        if (maps.exists()) {
            try (BufferedReader r = new BufferedReader(new FileReader(maps))) {
                String line;
                while ((line = r.readLine()) != null) {
                    int i = line.indexOf('/');
                    if (i < 0) continue;
                    String p = line.substring(i).trim();
                    if (!p.contains(".so") || p.startsWith(jh) || p.contains("fenvix")) continue;
                    if (p.startsWith("/usr/lib") || p.startsWith("/lib")) continue; // system libraries: the image
                    libs.add(p);
                }
            } catch (Exception ignored) {
                // no maps
            }
        }
        for (String l : libs) {
            String k = Deps.norm(l);
            m.put("native:" + (k == null ? l : k), Deps.fileState(l));
        }
        return m;
    }

    /** Configuration: junit-platform.properties, classpath order, build-tool test settings. */
    public static Map<String, String> config() {
        Map<String, String> m = new TreeMap<>();
        try {
            ClassLoader cl = ClassLoader.getSystemClassLoader();
            Enumeration<URL> e = cl.getResources("junit-platform.properties");
            int i = 0;
            while (e.hasMoreElements()) {
                URL u = e.nextElement();
                try (InputStream in = u.openStream()) {
                    m.put("junit-platform.properties#" + (i++), Native.digest(Compat.readAll(in)));
                }
            }
        } catch (Exception ignored) {
            // none
        }
        StringBuilder cp = new StringBuilder();
        for (String p : System.getProperty("java.class.path", "").split(File.pathSeparator)) {
            if (p.contains("fenvix")) continue;
            String k = Deps.norm(p);
            cp.append(k == null ? "tmp" : k).append('\n');
        }
        m.put("classpath", Native.digest(cp.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        m.put("build", System.getProperty("fenvix.config", ""));
        return m;
    }
}
