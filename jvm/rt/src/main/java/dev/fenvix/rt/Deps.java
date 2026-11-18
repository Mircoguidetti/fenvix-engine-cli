package dev.fenvix.rt;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Skip-with-proof capture: per test, what it depends on.
 *
 * <ul>
 *   <li>code executed: every class one of whose methods ran (method-entry probe
 *       inserted by the agent) or whose static fields were read, with the digest
 *       of its class-file bytes;
 *   <li>files read (content digest when first opened), files written, existence
 *       probes, directory listings, classpath resources;
 *   <li>environment variables and system properties read (name and value digest);
 *   <li>external network (makes the test not reusable);
 *   <li>tests it depends on through static fields written by an earlier test.
 * </ul>
 *
 * Everything outside any test (static initialisers run during discovery, the
 * runner's setup) goes to the {@code <session>} scope, everything inside a
 * class container but outside its tests ({@code @BeforeAll}) to the class
 * scope; a test's key is the union of its own scope and its enclosing scopes.
 * The runtime identity and the configuration are per JVM (the {@code jvm}
 * record). Output: one JSON line per scope in {@code <out>/deps/<module>-<pid>.jsonl}.
 */
public final class Deps {
    private Deps() {}

    // ------------------------------------------------------------ class ids
    static final Map<String, Integer> IDS = new HashMap<>();
    static final List<String> NAMES = new ArrayList<>();
    static volatile int[] TOUCH = new int[4096];
    static volatile int[] STOUCH = new int[4096];
    static volatile int EPOCH = 1;
    static String[] LAST_WRITER = new String[4096];
    /** class name -> {digest, source} for every class transformed by the agent. */
    static final ConcurrentHashMap<String, String[]> CLASSES = new ConcurrentHashMap<>();

    /** Id of a class (internal name), assigned at instrumentation time. */
    public static synchronized int classId(String internalName) {
        Integer i = IDS.get(internalName);
        if (i != null) return i;
        int id = NAMES.size();
        NAMES.add(internalName);
        IDS.put(internalName, id);
        if (id >= TOUCH.length) {
            int n = Math.max(id + 1, TOUCH.length * 2);
            TOUCH = Arrays.copyOf(TOUCH, n);
            STOUCH = Arrays.copyOf(STOUCH, n);
            LAST_WRITER = Arrays.copyOf(LAST_WRITER, n);
        }
        return id;
    }

    /** Called by the agent for every class it sees: digest of the original bytes and where they came from. */
    public static void classDefined(String internalName, String digest, String source) {
        CLASSES.put(internalName, new String[] {digest, source == null ? "" : source});
    }

    // --------------------------------------------------------------- scopes
    static final class Scope {
        final String id;
        final String kind;
        final Scope parent;
        final TreeSet<Integer> classes = new TreeSet<>();
        final TreeMap<String, String> files = new TreeMap<>();
        final TreeMap<String, String> env = new TreeMap<>();
        final TreeMap<String, String> props = new TreeMap<>();
        final TreeSet<String> net = new TreeSet<>();
        final TreeSet<String> after = new TreeSet<>();
        final TreeSet<String> resources = new TreeSet<>();
        boolean written;
        long t0 = System.nanoTime();

        Scope(String id, String kind, Scope parent) {
            this.id = id;
            this.kind = kind;
            this.parent = parent;
        }

        String testId() {
            return kind.equals("test") ? id : null;
        }
    }

    static final Scope SESSION = new Scope("<session>", "session", null);
    static volatile Scope CUR = SESSION;
    static final Object L = new Object();
    static Writer out;
    static final Map<String, String> DIGESTS = new ConcurrentHashMap<>();

    static void setScope(Scope s) {
        synchronized (L) {
            CUR = s;
            EPOCH++;
        }
    }

    public static void beginContainer(String id) {
        if (!Det.DEPS) return;
        setScope(new Scope(id, "container", CUR));
    }

    public static void endContainer() {
        if (!Det.DEPS) return;
        Scope s = CUR;
        if (s.parent == null) return;
        write(s, null);
        setScope(s.parent);
    }

    static void beginTest(String id) {
        setScope(new Scope(id, "test", CUR));
    }

    static void endTest(String outcome) {
        Scope s = CUR;
        if (!s.kind.equals("test")) return;
        write(s, outcome);
        setScope(s.parent);
    }

    // --------------------------------------------------------------- probes
    static void touch(int id) {
        int[] t = TOUCH;
        int e = EPOCH;
        if (id < t.length && t[id] == e) return;
        synchronized (L) {
            if (id < TOUCH.length) TOUCH[id] = EPOCH;
            CUR.classes.add(id);
        }
    }

    static void touchStaticRead(int id) {
        int[] t = STOUCH;
        int e = EPOCH;
        if (id < t.length && t[id] == e) return;
        synchronized (L) {
            if (id < STOUCH.length) STOUCH[id] = EPOCH;
            Scope s = CUR;
            s.classes.add(id);
            String w = id < LAST_WRITER.length ? LAST_WRITER[id] : null;
            String me = s.testId();
            if (w != null && me != null && !w.equals(me)) s.after.add(w);
        }
    }

    static void wroteStatic(int id) {
        synchronized (L) {
            Scope s = CUR;
            s.classes.add(id);
            String me = s.testId();
            if (me != null && id < LAST_WRITER.length) LAST_WRITER[id] = me;
        }
    }

    static String norm(String path) {
        try {
            String p = new File(path).getAbsoluteFile().toPath().normalize().toString();
            String root = Det.ROOT;
            if (p.equals(root)) return "root:.";
            if (p.startsWith(root + File.separator)) return "root:" + p.substring(root.length() + 1).replace(File.separatorChar, '/');
            String tmp = System.getProperty("java.io.tmpdir", "/tmp");
            if (p.startsWith(new File(tmp).getAbsolutePath() + File.separator)) return null; // per-test temporary files
            String jh = System.getProperty("java.home");
            if (jh != null && p.startsWith(jh)) return null; // runtime identity
            if (p.startsWith("/proc/") || p.startsWith("/dev/") || p.startsWith("/sys/")) return "sys:" + p;
            return "abs:" + p;
        } catch (RuntimeException e) {
            return "abs:" + path;
        }
    }

    static String fileState(String abs) {
        File f = new File(abs);
        if (!f.exists()) return "absent";
        if (f.isDirectory()) return "dir";
        long len = f.length();
        String key = abs + "|" + len + "|" + f.lastModified();
        String d = DIGESTS.get(key);
        if (d == null) {
            d = (len > (512L << 20)) ? "big:" + len : Native.isLoaded() ? Native.digestFile(abs) : "?";
            if (d == null) d = "unreadable";
            DIGESTS.put(key, d);
        }
        return "file:" + d;
    }

    static void opened(String path, String mode) {
        String k = norm(path);
        if (k == null) return;
        synchronized (L) {
            Scope s = CUR;
            String prev = s.files.get(k);
            if (mode.equals("r")) {
                if (prev == null || prev.startsWith("probe:")) s.files.put(k, "read:" + fileState(new File(path).getAbsolutePath()));
            } else {
                // written (or read-write): the test changes its own input; never reused
                s.files.put(k, "write");
                s.written = true;
            }
        }
    }

    static void probed(String path) {
        String k = norm(path);
        if (k == null) return;
        synchronized (L) {
            Scope s = CUR;
            if (s.files.containsKey(k)) return;
            File f = new File(path);
            s.files.put(k, "probe:" + (!f.exists() ? "absent" : f.isDirectory() ? "dir" : "file"));
        }
    }

    static void listed(String dir, String[] names) {
        String k = norm(dir);
        if (k == null) return;
        String[] sorted = names.clone();
        Arrays.sort(sorted);
        String d = Det.digestNames(Arrays.asList(sorted));
        synchronized (L) {
            CUR.files.putIfAbsent(k + "/", "list:" + d);
        }
    }

    public static void resource(String name, URL url) {
        if (!Det.DEPS || name == null) return;
        if (!Det.enter()) return;
        try {
            if (Caller.user() == null) return;
            synchronized (L) {
                CUR.resources.add(name + "=" + (url == null ? "absent" : resKey(url)));
            }
        } finally {
            Det.exit();
        }
    }

    static String resKey(URL u) {
        String s = u.toString();
        if (s.startsWith("file:")) {
            try {
                String p = new File(u.toURI()).getPath();
                String k = norm(p);
                return (k == null ? s : k) + "@" + fileState(p);
            } catch (Exception e) {
                return s;
            }
        }
        if (s.startsWith("jar:file:")) {
            int bang = s.indexOf("!/");
            if (bang > 0) {
                String jar = s.substring("jar:file:".length(), bang);
                String k = norm(jar);
                return "jar:" + (k == null ? jar : k) + "!" + s.substring(bang + 1) + "@" + fileState(jar);
            }
        }
        return s;
    }

    static void env(String name, String value) {
        if (!Det.DEPS) return;
        synchronized (L) {
            CUR.env.put(name, value == null ? "unset" : digestValue(value));
        }
    }

    static void prop(String name, String value) {
        if (!Det.DEPS) return;
        synchronized (L) {
            CUR.props.put(name, value == null ? "unset" : digestValue(value));
        }
    }

    static String digestValue(String v) {
        return Native.isLoaded() ? Native.digest(v.getBytes(StandardCharsets.UTF_8)) : Integer.toHexString(v.hashCode());
    }

    static void network(String what) {
        synchronized (L) {
            CUR.net.add(what);
        }
    }

    // --------------------------------------------------------------- output
    static String outPath() {
        String mod = Det.MODULE.isEmpty() ? "root" : Det.MODULE.replaceAll("[^A-Za-z0-9_.-]", "_");
        return Det.OUT + "/deps/" + mod + "-" + Compat.pid() + ".jsonl";
    }

    static void write(Scope s, String outcome) {
        StringBuilder sb = new StringBuilder(1024);
        sb.append("{\"type\":\"").append(s.kind).append("\",\"id\":");
        Json.str(sb, s.id);
        sb.append(",\"module\":");
        Json.str(sb, Det.MODULE);
        if (outcome != null) {
            sb.append(",\"outcome\":");
            Json.str(sb, outcome);
        }
        sb.append(",\"ms\":").append((System.nanoTime() - s.t0) / 1_000_000.0);
        List<String> scopes = new ArrayList<>();
        for (Scope p = s.parent; p != null; p = p.parent) scopes.add(p.id);
        sb.append(",\"scopes\":");
        Json.strs(sb, scopes);
        List<String> cls = new ArrayList<>();
        synchronized (Deps.class) {
            for (int id : s.classes) cls.add(NAMES.get(id));
        }
        sb.append(",\"classes\":");
        Json.strs(sb, cls);
        sb.append(",\"files\":");
        Json.map(sb, s.files);
        sb.append(",\"resources\":");
        Json.strs(sb, new ArrayList<>(s.resources));
        sb.append(",\"env\":");
        Json.map(sb, s.env);
        sb.append(",\"props\":");
        Json.map(sb, s.props);
        sb.append(",\"net\":");
        Json.strs(sb, new ArrayList<>(s.net));
        sb.append(",\"after\":");
        Json.strs(sb, new ArrayList<>(s.after));
        sb.append(",\"written\":").append(s.written);
        sb.append("}\n");
        emit(sb.toString());
    }

    static void emit(String line) {
        synchronized (L) {
            try {
                if (out == null) {
                    File f = new File(outPath());
                    f.getParentFile().mkdirs();
                    out = new OutputStreamWriter(new FileOutputStream(f, true), StandardCharsets.UTF_8);
                }
                out.write(line);
                out.flush();
            } catch (IOException e) {
                System.err.println("fenvix: cannot write deps: " + e);
            }
        }
    }

    /** End of the JVM (or of the test plan): session scope, class table, runtime identity. */
    public static void finish(Map<String, String> runtime, Map<String, String> config) {
        if (!Det.DEPS) return;
        write(SESSION, null);
        StringBuilder sb = new StringBuilder(1 << 16);
        sb.append("{\"type\":\"jvm\",\"module\":");
        Json.str(sb, Det.MODULE);
        sb.append(",\"root\":");
        Json.str(sb, Det.ROOT);
        sb.append(",\"runtime\":");
        Json.map(sb, new TreeMap<>(runtime));
        sb.append(",\"config\":");
        Json.map(sb, new TreeMap<>(config));
        Map<String, String> cls = new TreeMap<>();
        for (Map.Entry<String, String[]> e : CLASSES.entrySet()) {
            String src = e.getValue()[1];
            String k = src.isEmpty() ? "" : norm(src);
            cls.put(e.getKey(), e.getValue()[0] + " " + (k == null ? src : k));
        }
        sb.append(",\"classes\":");
        Json.map(sb, cls);
        // every variable and property this JVM could read (value digests), and the class path
        Map<String, String> env = new TreeMap<>();
        for (Map.Entry<String, String> e : System.getenv().entrySet()) env.put(e.getKey(), digestValue(e.getValue()));
        sb.append(",\"env_all\":");
        Json.map(sb, env);
        Map<String, String> props = new TreeMap<>();
        for (String k : System.getProperties().stringPropertyNames()) props.put(k, digestValue(String.valueOf(System.getProperty(k))));
        sb.append(",\"props_all\":");
        Json.map(sb, props);
        List<String> cp = new ArrayList<>();
        for (String p : System.getProperty("java.class.path", "").split(File.pathSeparator)) if (!p.isEmpty()) cp.add(p);
        sb.append(",\"classpath\":");
        Json.strs(sb, cp);
        sb.append("}\n");
        emit(sb.toString());
    }

    public static Map<String, String> newMap() {
        return new LinkedHashMap<>();
    }
}
