package dev.fenvix.rt;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.concurrent.ConcurrentHashMap;
import java.util.jar.JarFile;
import java.util.jar.Manifest;

/**
 * Skip-with-proof capture: per test, what it depends on.
 *
 * <ul>
 *   <li>code: every class one of whose methods ran (method-entry probe inserted by
 *       the agent), whose static fields were accessed (the symbolic owner and the
 *       declaring class, resolved like the JVM resolves the field), whose reflective
 *       metadata was read (Class.getAnnotation*, getDeclared*, annotation types parsed
 *       for it), with the digest of its class-file bytes;
 *   <li>static initialisers: what a class's {@code <clinit>} depended on (classes,
 *       files, resources, ...) is added to every scope that later touches the class,
 *       not only to the scope that happened to initialise it;
 *   <li>class lookups by name ({@code Class.forName}, {@code ClassLoader.loadClass}),
 *       found or not; classpath resources ({@code getResource}, found or not, and
 *       {@code getResources}: every location);
 *   <li>files read (content digest when first opened), files written, existence
 *       probes, directory listings; reads made by the test infrastructure on behalf
 *       of a test (argument sources such as {@code @CsvFileSource}) count;
 *   <li>environment variables and system properties read (name and value digest);
 *   <li>not keyable, so the test is never reused: external network, child processes,
 *       native code of the project (a library loaded or a native method called);
 *   <li>shared state: whether the scope read static state that another test could
 *       have changed ({@code mut}: a non-final static field, or a final one holding a
 *       mutable object), whether it wrote a static field, and the tests that wrote
 *       the static fields it read ({@code after}). The decider makes a test that
 *       read shared state depend on every test that ran before it in its JVM.
 * </ul>
 *
 * Everything outside any test (static initialisers run during discovery, the
 * runner's setup) goes to the {@code <session>} scope, everything inside a
 * class container but outside its tests ({@code @BeforeAll}) to the class
 * scope; a test's key is the union of its own scope and its enclosing scopes.
 * The runtime identity and the configuration are per JVM (the {@code jvm}
 * record). Output: one JSON line per scope in {@code <out>/deps/<module>-<pid>.jsonl},
 * test records in execution order.
 */
public final class Deps {
    private Deps() {}

    // ------------------------------------------------------------ class ids
    static final Map<String, Integer> IDS = new HashMap<>();
    static final List<String> NAMES = new ArrayList<>();
    static volatile int[] TOUCH = new int[4096];
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
            LAST_WRITER = Arrays.copyOf(LAST_WRITER, n);
        }
        return id;
    }

    static synchronized Integer idOf(String internalName) {
        return IDS.get(internalName);
    }

    static synchronized String nameOf(int id) {
        return id >= 0 && id < NAMES.size() ? NAMES.get(id) : null;
    }

    /** Called by the agent for every class it sees: digest of the original bytes and where they came from. */
    public static void classDefined(String internalName, String digest, String source) {
        CLASSES.put(internalName, new String[] {digest, source == null ? "" : source});
    }

    // ------------------------------------------------------ class structure
    /** What the agent read from a class file: enough to resolve a static field like the JVM does. */
    static final class Info {
        final String superName;
        final String[] interfaces;
        final boolean isFinal;
        /** declared field name -> access flags */
        final Map<String, Integer> fields;
        /** every instance field is final and of an immutable JDK type or primitive */
        final boolean immutableInstance;
        /** descriptors of the final instance fields of a user type (immutable when that type is) */
        final String[] refFields;

        Info(String superName, String[] interfaces, boolean isFinal, Map<String, Integer> fields, boolean immutableInstance, String[] refFields) {
            this.superName = superName;
            this.interfaces = interfaces == null ? new String[0] : interfaces;
            this.isFinal = isFinal;
            this.fields = fields;
            this.immutableInstance = immutableInstance;
            this.refFields = refFields;
        }
    }

    static final ConcurrentHashMap<String, Info> INFO = new ConcurrentHashMap<>();

    /**
     * Registered by the agent when it transforms a class. {@code fields}: name + "\t" + access flags;
     * {@code immutableInstance}: every instance field final and of a primitive or immutable JDK type.
     */
    public static void classInfo(String name, String superName, String[] interfaces, int access, String[] fields, boolean immutableInstance,
            String[] refFields) {
        Map<String, Integer> f = new HashMap<>();
        for (String s : fields) {
            int t = s.indexOf('\t');
            f.put(s.substring(0, t), Integer.parseInt(s.substring(t + 1)));
        }
        INFO.put(name, new Info(superName, interfaces, (access & Modifier.FINAL) != 0, f, immutableInstance, refFields));
    }

    /** Immutable JDK types (field descriptors): a final static field of one of them is a constant. */
    static final Set<String> IMMUTABLE_DESC = new HashSet<>(Arrays.asList(
            "Ljava/lang/String;", "Ljava/lang/Integer;", "Ljava/lang/Long;", "Ljava/lang/Short;", "Ljava/lang/Byte;",
            "Ljava/lang/Character;", "Ljava/lang/Boolean;", "Ljava/lang/Float;", "Ljava/lang/Double;", "Ljava/math/BigInteger;",
            "Ljava/math/BigDecimal;", "Ljava/util/regex/Pattern;", "Ljava/util/UUID;", "Ljava/lang/Class;", "Ljava/util/Locale;",
            "Ljava/nio/charset/Charset;", "Ljava/time/Duration;", "Ljava/time/Instant;", "Ljava/time/LocalDate;", "Ljava/time/LocalTime;",
            "Ljava/time/LocalDateTime;", "Ljava/time/ZonedDateTime;", "Ljava/time/OffsetDateTime;", "Ljava/time/OffsetTime;",
            "Ljava/time/Period;", "Ljava/time/Year;", "Ljava/time/YearMonth;", "Ljava/time/MonthDay;", "Ljava/time/ZoneOffset;",
            "Ljava/time/ZoneId;", "Ljava/time/format/DateTimeFormatter;", "Ljava/util/concurrent/TimeUnit;",
            "Ljava/time/temporal/ChronoUnit;", "Ljava/math/RoundingMode;", "Ljava/math/MathContext;"));

    /** Immutable JDK classes (runtime values). */
    static final Set<String> IMMUTABLE_CLASS = new HashSet<>(Arrays.asList(
            "java.lang.String", "java.lang.Integer", "java.lang.Long", "java.lang.Short", "java.lang.Byte", "java.lang.Character",
            "java.lang.Boolean", "java.lang.Float", "java.lang.Double", "java.math.BigInteger", "java.math.BigDecimal",
            "java.util.regex.Pattern", "java.util.UUID", "java.lang.Class", "java.util.Locale", "java.time.Duration", "java.time.Instant",
            "java.time.LocalDate", "java.time.LocalTime", "java.time.LocalDateTime", "java.time.ZonedDateTime", "java.time.OffsetDateTime",
            "java.time.OffsetTime", "java.time.Period", "java.time.Year", "java.time.YearMonth", "java.time.MonthDay",
            "java.time.ZoneOffset", "java.time.ZoneRegion", "java.time.format.DateTimeFormatter", "java.math.MathContext",
            "java.util.Collections$EmptyList", "java.util.Collections$EmptySet", "java.util.Collections$EmptyMap"));

    public static boolean immutableDesc(String desc) {
        return desc.length() == 1 || IMMUTABLE_DESC.contains(desc);
    }

    /** A final class (or an enum without constant bodies) whose instances cannot change: a field of this type holds an immutable value. */
    static boolean immutableUserClass(String internalName, int depth) {
        Info i = INFO.get(internalName);
        return i != null && i.isFinal && instancesImmutable(internalName, depth);
    }

    /**
     * Objects whose runtime class is exactly this class cannot change: every instance field (its own
     * and its superclasses') is final and holds a primitive, an immutable JDK type, or a final user
     * type whose instances cannot change.
     */
    static boolean instancesImmutable(String internalName, int depth) {
        if (depth > 8) return false;
        Info i = INFO.get(internalName);
        if (i == null || !i.immutableInstance) return false;
        for (String d : i.refFields) {
            if (!d.startsWith("L") || !immutableUserClass(d.substring(1, d.length() - 1), depth + 1)) return false;
        }
        String s = i.superName;
        if (s == null || s.equals("java/lang/Object") || s.equals("java/lang/Enum") || s.equals("java/lang/Record")) return true;
        return instancesImmutable(s, depth + 1);
    }

    static boolean immutableValue(Object v) {
        if (v == null) return true;
        Class<?> c = v.getClass();
        if (c.isArray()) return java.lang.reflect.Array.getLength(v) == 0;
        if (IMMUTABLE_CLASS.contains(c.getName())) return true;
        if (Infra.isJdk(c)) {
            // a JDK enum constant
            return c.isEnum() || (c.getSuperclass() != null && c.getSuperclass().isEnum());
        }
        // the runtime class is known: its finality does not matter, its fields do
        return instancesImmutable(c.getName().replace('.', '/'), 0);
    }

    // --------------------------------------------------------- static sites
    /** A GETSTATIC/PUTSTATIC site in code under test, resolved at its first execution. */
    static final class Site {
        final String owner, name, desc;
        final boolean put;
        volatile boolean resolved;
        int[] ids = new int[0];
        int declaring = -1;
        boolean finalField;
        boolean infra;
        /** final field holding an immutable value (decided once: the value never changes) */
        Boolean constant;

        Site(String owner, String name, String desc, boolean put) {
            this.owner = owner;
            this.name = name;
            this.desc = desc;
            this.put = put;
        }
    }

    static final List<Site> SITES = new ArrayList<>();
    static volatile int[] SITE_EPOCH = new int[4096];

    /** Register a static field access site (agent, at rewrite time). */
    public static synchronized int staticSite(String owner, String name, String desc, boolean put) {
        int id = SITES.size();
        SITES.add(new Site(owner, name, desc, put));
        if (id >= SITE_EPOCH.length) SITE_EPOCH = Arrays.copyOf(SITE_EPOCH, Math.max(id + 1, SITE_EPOCH.length * 2));
        return id;
    }

    static synchronized Site site(int id) {
        return SITES.get(id);
    }

    /** JVM field resolution (JVMS 5.4.3.2) over the classes the agent saw: declared, superinterfaces, superclass. */
    static String declaringClass(String c, String field, int depth) {
        if (c == null || depth > 64) return null;
        Info i = INFO.get(c);
        if (i == null) return null;
        if (i.fields.containsKey(field)) return c;
        for (String itf : i.interfaces) {
            String r = declaringClass(itf, field, depth + 1);
            if (r != null) return r;
        }
        return declaringClass(i.superName, field, depth + 1);
    }

    /** Every supertype the agent saw (conservative fallback when the field cannot be resolved). */
    static void supers(String c, Set<String> out, int depth) {
        if (c == null || depth > 64 || !out.add(c)) return;
        Info i = INFO.get(c);
        if (i == null) return;
        for (String itf : i.interfaces) supers(itf, out, depth + 1);
        supers(i.superName, out, depth + 1);
    }

    static void resolve(Site s) {
        if (s.resolved) return;
        synchronized (s) {
            if (s.resolved) return;
            Boolean ownerInfra = Infra.knownInfra(s.owner);
            if (ownerInfra != null && ownerInfra) {
                s.infra = true;
            } else {
                String d = declaringClass(s.owner, s.name, 0);
                Set<String> names = new TreeSet<>();
                names.add(s.owner);
                if (d != null) {
                    names.add(d);
                    Info di = INFO.get(d);
                    Integer acc = di == null ? null : di.fields.get(s.name);
                    s.finalField = acc != null && (acc & Modifier.FINAL) != 0 && (acc & Modifier.STATIC) != 0;
                } else {
                    // not resolvable over what the agent saw: every known supertype, a mutable field
                    supers(s.owner, names, 0);
                    s.finalField = false;
                }
                int[] ids = new int[names.size()];
                int k = 0;
                for (String n : names) ids[k++] = classId(n);
                s.ids = ids;
                s.declaring = classId(d != null ? d : s.owner);
                if (s.finalField && immutableDesc(s.desc)) s.constant = Boolean.TRUE;
                else if (s.finalField && s.desc.startsWith("L") && immutableUserClass(s.desc.substring(1, s.desc.length() - 1), 0)) {
                    s.constant = Boolean.TRUE;
                } else if (!s.finalField) {
                    s.constant = Boolean.FALSE;
                }
            }
            s.resolved = true;
        }
    }

    /** After a GETSTATIC of a primitive field (Det.staticRead). */
    static void staticRead(int sid) {
        int[] ep = SITE_EPOCH;
        int e = EPOCH;
        if (sid < ep.length && ep[sid] == e) return;
        Site s = site(sid);
        resolve(s);
        if (s.infra) return;
        synchronized (L) {
            if (sid < SITE_EPOCH.length) SITE_EPOCH[sid] = EPOCH;
            readInto(s, s.constant == null || !s.constant);
        }
    }

    /** After a GETSTATIC of a reference field: the value decides whether a final field is a constant. */
    static void staticRefRead(Object value, int sid) {
        int[] ep = SITE_EPOCH;
        int e = EPOCH;
        if (sid < ep.length && ep[sid] == e) return;
        Site s = site(sid);
        resolve(s);
        if (s.infra) return;
        if (s.constant == null) {
            boolean c;
            try {
                c = immutableValue(value);
            } catch (Throwable t) {
                c = false;
            }
            // a final field's value does not change once its class is initialised
            s.constant = c;
        }
        synchronized (L) {
            if (sid < SITE_EPOCH.length) SITE_EPOCH[sid] = EPOCH;
            readInto(s, !s.constant);
        }
    }

    static void readInto(Site s, boolean mutable) {
        Scope cur = CUR;
        String me = cur.testId();
        String w = s.declaring >= 0 && s.declaring < LAST_WRITER.length ? LAST_WRITER[s.declaring] : null;
        for (Scope t : targets()) {
            for (int id : s.ids) addClass(t, id);
            if (mutable) {
                t.mut = true;
                t.mutClasses.add(s.declaring);
            }
        }
        if (w != null && me != null && !w.equals(me)) cur.after.add(w);
    }

    /** After a PUTSTATIC (Det.staticWrite). */
    static void staticWrite(int sid) {
        Site s = site(sid);
        resolve(s);
        if (s.infra) return;
        synchronized (L) {
            Scope cur = CUR;
            for (Scope t : targets()) {
                for (int id : s.ids) addClass(t, id);
                t.swrite = true;
            }
            String me = cur.testId();
            if (me != null && s.declaring >= 0 && s.declaring < LAST_WRITER.length) LAST_WRITER[s.declaring] = me;
        }
    }

    // -------------------------------------------------- static initialisers
    /** Active {@code <clinit>} frames of this thread (innermost last). */
    static final ThreadLocal<ArrayList<Scope>> FRAMES = new ThreadLocal<ArrayList<Scope>>() {
        @Override
        protected ArrayList<Scope> initialValue() {
            return new ArrayList<>();
        }
    };
    /** class id -> what its static initialiser depended on. */
    static final Map<Integer, Scope> INIT = new HashMap<>();
    static final Map<Integer, Set<Integer>> ANNOS = new HashMap<>();

    static void clinitEnter(int id) {
        synchronized (L) {
            FRAMES.get().add(new Scope("<clinit>" + id, "clinit", null));
            EPOCH++; // fast paths must record into the new frame
        }
    }

    static void clinitExit(int id) {
        synchronized (L) {
            ArrayList<Scope> f = FRAMES.get();
            String key = "<clinit>" + id;
            for (int i = f.size() - 1; i >= 0; i--) {
                Scope s = f.get(i);
                if (s.id.equals(key)) {
                    while (f.size() > i) f.remove(f.size() - 1);
                    INIT.put(id, s);
                    break;
                }
            }
            EPOCH++;
        }
    }

    /** CUR and the active clinit frames of this thread (caller holds L). */
    static List<Scope> targets() {
        ArrayList<Scope> f = FRAMES.get();
        if (f.isEmpty()) return Collections.singletonList(CUR);
        List<Scope> l = new ArrayList<>(f.size() + 1);
        l.add(CUR);
        l.addAll(f);
        return l;
    }

    /** Add a class (and what its initialiser and its annotations depended on) to a scope (caller holds L). */
    static void addClass(Scope t, int id) {
        if (!t.classes.add(id)) return;
        Scope init = INIT.get(id);
        if (init != null && init != t) merge(t, init);
        Set<Integer> an = ANNOS.get(id);
        if (an != null) for (int a : an) addClass(t, a);
    }

    static void merge(Scope t, Scope s) {
        for (int c : s.classes) addClass(t, c);
        for (Map.Entry<String, String> e : s.files.entrySet()) t.files.putIfAbsent(e.getKey(), e.getValue());
        t.resources.addAll(s.resources);
        for (Map.Entry<String, String> e : s.env.entrySet()) t.env.putIfAbsent(e.getKey(), e.getValue());
        for (Map.Entry<String, String> e : s.props.entrySet()) t.props.putIfAbsent(e.getKey(), e.getValue());
        t.net.addAll(s.net);
        t.lookups.addAll(s.lookups);
        t.proc.addAll(s.proc);
        t.nat.addAll(s.nat);
        t.written |= s.written;
        t.mut |= s.mut;
        t.mutClasses.addAll(s.mutClasses);
        t.swrite |= s.swrite;
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
        final TreeSet<String> lookups = new TreeSet<>();
        final TreeSet<String> proc = new TreeSet<>();
        final TreeSet<String> nat = new TreeSet<>();
        /** classes whose mutable static state was read (why mut is set) */
        final TreeSet<Integer> mutClasses = new TreeSet<>();
        boolean written;
        boolean mut;
        boolean swrite;
        /** container: its tests share one test instance (JUnit Jupiter PER_CLASS, TestNG, unknown engines) */
        boolean shared;
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
        beginContainer(id, false);
    }

    /** A class (or other) container; {@code shared}: its tests run on one shared test instance. */
    public static void beginContainer(String id, boolean shared) {
        if (!Det.DEPS) return;
        Scope s = new Scope(id, "container", CUR);
        s.shared = shared;
        setScope(s);
    }

    public static void endContainer() {
        if (!Det.DEPS) return;
        Scope s = CUR;
        // a test scope still open here lost its end event: it is not a test record (no outcome)
        while (s.kind.equals("test") && s.parent != null) s = s.parent;
        if (s.parent == null) return;
        write(s, null);
        setScope(s.parent);
    }

    /** The innermost scope that is not a test (tests never nest). */
    static Scope container() {
        Scope s = CUR;
        while (s.kind.equals("test") && s.parent != null) s = s.parent;
        return s;
    }

    static void beginTest(String id) {
        if (PROPS_START == null) {
            synchronized (L) {
                if (PROPS_START == null) PROPS_START = propsNow();
            }
        }
        setScope(new Scope(id, "test", container()));
    }

    static void endTest(String outcome) {
        Scope s = CUR;
        if (!s.kind.equals("test")) return;
        write(s, outcome);
        setScope(s.parent);
    }

    /** True while recording into the session scope (outside every test and class container). */
    static boolean inSession() {
        return CUR == SESSION;
    }

    // --------------------------------------------------------------- probes
    static void touch(int id) {
        int[] t = TOUCH;
        int e = EPOCH;
        if (id < t.length && t[id] == e) return;
        synchronized (L) {
            if (id < TOUCH.length) TOUCH[id] = EPOCH;
            for (Scope s : targets()) addClass(s, id);
        }
    }

    /** A class whose reflective metadata (annotations, members, generic signature) was read. */
    public static void reflected(Class<?> c) {
        if (!Det.DEPS || c == null) return;
        if (!Det.enter()) return;
        try {
            reflectedClass(c);
        } finally {
            Det.exit();
        }
    }

    public static void reflected2(Class<?> c, Class<?> other) {
        if (!Det.DEPS) return;
        if (!Det.enter()) return;
        try {
            reflectedClass(c);
            reflectedClass(other);
        } finally {
            Det.exit();
        }
    }

    static void reflectedClass(Class<?> c) {
        if (c == null || Infra.isJdk(c)) return;
        Integer id = idOf(c.getName().replace('.', '/'));
        if (id == null) return; // not transformed: infrastructure, generated
        // the runner reflecting over test classes during discovery is not a test's input
        if (inSession() && Caller.kind() != Caller.USER) return;
        synchronized (L) {
            for (Scope s : targets()) addClass(s, id);
        }
    }

    /** A reflective static field access (Field.get / set on a static field). */
    public static void fieldAccess(Field f, boolean write) {
        if (!Det.DEPS || f == null) return;
        if (!Modifier.isStatic(f.getModifiers())) return;
        if (!Det.enter()) return;
        try {
            Class<?> c = f.getDeclaringClass();
            if (Infra.isJdk(c)) return;
            Integer id = idOf(c.getName().replace('.', '/'));
            if (id == null) return;
            if (inSession() && Caller.kind() != Caller.USER) return;
            synchronized (L) {
                for (Scope s : targets()) {
                    addClass(s, id);
                    if (write) s.swrite = true;
                    else s.mut = true;
                }
            }
        } finally {
            Det.exit();
        }
    }

    public static void fieldGet(Field f) {
        fieldAccess(f, false);
    }

    public static void fieldSet(Field f) {
        fieldAccess(f, true);
    }

    /** MethodHandles.Lookup.find*(refc, ...): the class is read reflectively; static getters/var handles read shared state. */
    public static void lookupFind(Class<?> refc) {
        reflected(refc);
    }

    public static void lookupStatic(Class<?> refc) {
        if (!Det.DEPS || refc == null || Infra.isJdk(refc)) return;
        reflected(refc);
        synchronized (L) {
            for (Scope s : targets()) s.mut = true;
        }
    }

    /** Annotations parsed for {@code container} (a class, or the class declaring a member): their types. */
    public static void annotationsParsed(Map<?, ?> parsed, Class<?> container) {
        if (!Det.DEPS || parsed == null || container == null || parsed.isEmpty()) return;
        if (!Det.enter()) return;
        try {
            if (Infra.isJdk(container)) return;
            Integer cid = idOf(container.getName().replace('.', '/'));
            if (cid == null) return;
            List<Integer> types = new ArrayList<>();
            for (Object k : parsed.keySet()) {
                if (!(k instanceof Class)) continue;
                Class<?> a = (Class<?>) k;
                if (Infra.isJdk(a)) continue;
                Integer aid = idOf(a.getName().replace('.', '/'));
                if (aid != null) types.add(aid);
            }
            if (types.isEmpty()) return;
            synchronized (L) {
                Set<Integer> s = ANNOS.get(cid);
                if (s == null) {
                    s = new TreeSet<>();
                    ANNOS.put(cid, s);
                }
                s.addAll(types);
                for (Scope t : targets()) {
                    if (t.classes.contains(cid)) for (int a : types) addClass(t, a);
                }
            }
        } finally {
            Det.exit();
        }
    }

    /** Class.forName / ClassLoader.loadClass of a name: whether it was found is part of the key. */
    public static void classLookup(String name) {
        if (!Det.DEPS || name == null || name.isEmpty() || name.charAt(0) == '[') return;
        if (name.startsWith("java.") || name.startsWith("javax.") || name.startsWith("jdk.") || name.startsWith("sun.")
                || name.startsWith("com.sun.") || name.startsWith("dev.fenvix.")) {
            return;
        }
        if (!Det.enter()) return;
        try {
            if (inSession() && Caller.kind(true) != Caller.USER) return;
            synchronized (L) {
                for (Scope s : targets()) s.lookups.add(name.replace('.', '/'));
            }
        } finally {
            Det.exit();
        }
    }

    /** A child process: its inputs are invisible to the capture (the test is never reused). */
    public static void proc(String what) {
        if (!Det.DEPS) return;
        if (!Det.enter()) return;
        try {
            if (inSession() && Caller.kind() == Caller.INFRA) return;
            synchronized (L) {
                for (Scope s : targets()) s.proc.add(what);
            }
        } finally {
            Det.exit();
        }
    }

    /** A native library loaded by a non-JDK class, or a native method of the project called. */
    public static void nativeCode(String what) {
        if (!Det.DEPS) return;
        synchronized (L) {
            for (Scope s : targets()) s.nat.add(what);
        }
    }

    static void wroteStatic(int id) {
        synchronized (L) {
            Scope s = CUR;
            s.classes.add(id);
            s.swrite = true;
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

    /**
     * Whether a file access made by {@code kind} is recorded: code under test always;
     * the infrastructure's reads inside a test or class scope (it reads on behalf of the
     * test: argument sources, resources); never its writes (reports, tool output).
     */
    static boolean records(int kind, boolean write) {
        if (kind == Caller.USER) return true;
        if (kind == Caller.INFRA) return !write && !inSession();
        return false;
    }

    static void opened(String path, String mode) {
        String k = norm(path);
        if (k == null) return;
        synchronized (L) {
            for (Scope s : targets()) {
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
    }

    static void probed(String path) {
        String k = norm(path);
        if (k == null) return;
        synchronized (L) {
            File f = new File(path);
            String st = "probe:" + (!f.exists() ? "absent" : f.isDirectory() ? "dir" : "file");
            for (Scope s : targets()) {
                if (!s.files.containsKey(k)) s.files.put(k, st);
            }
        }
    }

    static void listed(String dir, String[] names) {
        String k = norm(dir);
        if (k == null) return;
        String[] sorted = names.clone();
        Arrays.sort(sorted);
        String d = Det.digestNames(Arrays.asList(sorted));
        synchronized (L) {
            for (Scope s : targets()) s.files.putIfAbsent(k + "/", "list:" + d);
        }
    }

    // ------------------------------------------------- classpath resources
    static volatile ClassLoader SYS;

    /** 0: the system class loader (the class path is the key); 1: the JDK's own loaders; 2: any other loader. */
    static int loaderKind(ClassLoader l) {
        if (l == null || l == Compat.platformLoader()) return 1;
        ClassLoader s = SYS;
        if (s == null) {
            try {
                s = ClassLoader.getSystemClassLoader();
                SYS = s;
            } catch (Throwable t) {
                return 2;
            }
        }
        if (l == s) return 0;
        // a parent of the system loader (JDK 8 extension loader)
        for (ClassLoader p = s.getParent(); p != null; p = p.getParent()) if (p == l) return 1;
        return 2;
    }

    /** At the return of {@code ClassLoader.getResource(name)}: found (location and state) or not. */
    public static void resource(URL url, ClassLoader loader, String name) {
        if (!Det.DEPS || name == null) return;
        if (!Det.enter()) return;
        try {
            int lk = loaderKind(loader);
            if (lk == 1) return; // JDK resources: runtime identity (and the parent step of every lookup)
            int kind = Caller.kind();
            if (!records(kind, false)) return;
            String n = name.startsWith("/") ? name.substring(1) : name;
            String v;
            if (lk == 2) v = "?";
            else if (url == null) v = "absent";
            else v = resKey(url);
            if (v == null) return;
            synchronized (L) {
                for (Scope s : targets()) s.resources.add(n + "=" + v);
            }
        } finally {
            Det.exit();
        }
    }

    /** At the return of {@code ClassLoader.getResources(name)}: every location, in order (ServiceLoader, factories). */
    public static Enumeration<URL> resources(Enumeration<URL> e, ClassLoader loader, String name) {
        if (!Det.DEPS || name == null || e == null) return e;
        if (!Det.enter()) return e;
        try {
            int lk = loaderKind(loader);
            if (lk == 1) return e;
            int kind = Caller.kind();
            if (!records(kind, false)) return e;
            List<URL> all = Collections.list(e);
            String n = name.startsWith("/") ? name.substring(1) : name;
            String v;
            if (lk == 2) {
                v = "?";
            } else {
                StringBuilder sb = new StringBuilder("all:");
                boolean first = true;
                for (URL u : all) {
                    String k = resKey(u);
                    if (k == null) continue; // the JDK's own (runtime identity) or fenvix
                    if (!first) sb.append('|');
                    first = false;
                    sb.append(k);
                }
                v = sb.toString();
            }
            synchronized (L) {
                for (Scope s : targets()) s.resources.add(n + "=" + v);
            }
            return Collections.enumeration(all);
        } finally {
            Det.exit();
        }
    }

    /** Location key of a resource URL ({@code path@state}); null for the JDK's own and fenvix's resources. */
    static String resKey(URL u) {
        String s = u.toString();
        if (s.startsWith("jrt:")) return null;
        if (s.startsWith("file:")) {
            try {
                String p = new File(u.toURI()).getPath();
                String jh = System.getProperty("java.home");
                if (jh != null && p.startsWith(jh)) return null;
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
                try {
                    jar = new File(new java.net.URI("file:" + jar)).getPath();
                } catch (Exception ignored) {
                    // keep the raw path
                }
                if (jar.contains("fenvix-agent")) return null;
                String jh = System.getProperty("java.home");
                if (jh != null && jar.startsWith(jh)) return null;
                String k = norm(jar);
                return "jar:" + (k == null ? jar : k) + "!" + s.substring(bang + 1) + "@" + fileState(jar);
            }
        }
        return s;
    }

    static void env(String name, String value) {
        if (!Det.DEPS) return;
        String v = value == null ? "unset" : digestValue(value);
        synchronized (L) {
            for (Scope s : targets()) s.env.put(name, v);
        }
    }

    static void prop(String name, String value) {
        if (!Det.DEPS) return;
        String v = value == null ? "unset" : digestValue(value);
        synchronized (L) {
            for (Scope s : targets()) s.props.put(name, v);
        }
    }

    /** System properties written by tests (System.setProperty, clearProperty, setProperties; "*": all). */
    static final TreeSet<String> PROPS_WRITTEN = new TreeSet<>();
    /** Every system property (value digest) when the first test started. */
    static volatile Map<String, String> PROPS_START;

    static Map<String, String> propsNow() {
        Map<String, String> props = new TreeMap<>();
        for (String k : System.getProperties().stringPropertyNames()) props.put(k, digestValue(String.valueOf(System.getProperty(k))));
        return props;
    }

    /**
     * A system property changed by code under test or inside a test: JVM-global state like a
     * static field. Its readers depend on the tests before them (decider: shared state).
     */
    public static void propWrite(String key) {
        if (!Det.DEPS || key == null) return;
        if (!Det.enter()) return;
        try {
            if (inSession() && Caller.kind() != Caller.USER) return; // the runner's own set-up
            synchronized (L) {
                PROPS_WRITTEN.add(key);
                for (Scope s : targets()) s.swrite = true;
            }
        } finally {
            Det.exit();
        }
    }

    public static void propWriteAll(java.util.Properties p) {
        propWrite("*");
    }

    static String digestValue(String v) {
        return Native.isLoaded() ? Native.digest(v.getBytes(StandardCharsets.UTF_8)) : Integer.toHexString(v.hashCode());
    }

    static void network(String what) {
        synchronized (L) {
            for (Scope s : targets()) s.net.add(what);
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
        // class lookups by name: found (a class the agent saw) or not
        Map<String, String> lk = new TreeMap<>();
        for (String n : s.lookups) {
            Boolean infra = Infra.knownInfra(n);
            if (infra != null && infra) continue;
            lk.put(n, CLASSES.containsKey(n) ? "present" : "absent");
        }
        sb.append(",\"lookups\":");
        Json.map(sb, lk);
        sb.append(",\"env\":");
        Json.map(sb, s.env);
        sb.append(",\"props\":");
        Json.map(sb, s.props);
        sb.append(",\"net\":");
        Json.strs(sb, new ArrayList<>(s.net));
        sb.append(",\"proc\":");
        Json.strs(sb, new ArrayList<>(s.proc));
        sb.append(",\"native\":");
        Json.strs(sb, new ArrayList<>(s.nat));
        sb.append(",\"after\":");
        Json.strs(sb, new ArrayList<>(s.after));
        sb.append(",\"written\":").append(s.written);
        sb.append(",\"mut\":").append(s.mut);
        sb.append(",\"swrite\":").append(s.swrite);
        List<String> mc = new ArrayList<>();
        synchronized (Deps.class) {
            for (int id : s.mutClasses) if (id >= 0 && id < NAMES.size()) mc.add(NAMES.get(id));
        }
        sb.append(",\"mut_classes\":");
        Json.strs(sb, mc);
        if (s.kind.equals("container")) sb.append(",\"shared\":").append(s.shared);
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

    /** JUnit configuration parameters seen by a test plan (key -> value digest), part of the configuration key. */
    static final Map<String, String> JUNIT_CONFIG = new TreeMap<>();

    public static void junitConfig(String key, String value) {
        if (!Det.DEPS || key == null) return;
        synchronized (JUNIT_CONFIG) {
            JUNIT_CONFIG.put(key, value == null ? "unset" : digestValue(value));
        }
    }

    /**
     * The class path of this JVM: java.class.path with manifest Class-Path entries
     * expanded (Surefire's manifest-only booter jar), fenvix's own jar left out.
     */
    public static List<String> classPath() {
        List<String> cp = new ArrayList<>();
        for (String p : System.getProperty("java.class.path", "").split(File.pathSeparator)) {
            if (p.isEmpty() || p.contains("fenvix-agent")) continue;
            File f = new File(p);
            List<String> extra = manifestClassPath(f);
            if (extra != null && f.getName().startsWith("surefirebooter")) {
                cp.addAll(extra); // the booter jar holds nothing but its manifest
                continue;
            }
            cp.add(f.getAbsolutePath());
            if (extra != null) cp.addAll(extra);
        }
        return cp;
    }

    static List<String> manifestClassPath(File jar) {
        if (!jar.isFile() || !jar.getName().endsWith(".jar")) return null;
        try (JarFile j = new JarFile(jar)) {
            Manifest m = j.getManifest();
            if (m == null) return null;
            String cp = m.getMainAttributes().getValue("Class-Path");
            if (cp == null || cp.trim().isEmpty()) return null;
            List<String> out = new ArrayList<>();
            for (String e : cp.trim().split("\\s+")) {
                try {
                    URL u = new URL(jar.toURI().toURL(), e);
                    if (!"file".equals(u.getProtocol())) continue;
                    String p = new File(u.toURI()).getAbsolutePath();
                    if (!p.contains("fenvix-agent")) out.add(p);
                } catch (Exception ignored) {
                    // not a file URL
                }
            }
            return out;
        } catch (IOException e) {
            return null;
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
        sb.append(",\"props_start\":");
        Json.map(sb, PROPS_START != null ? PROPS_START : props);
        synchronized (L) {
            sb.append(",\"props_written\":");
            Json.strs(sb, new ArrayList<>(PROPS_WRITTEN));
        }
        sb.append(",\"classpath\":");
        Json.strs(sb, classPath());
        sb.append(",\"root_dir\":");
        Json.str(sb, Det.ROOT);
        sb.append("}\n");
        emit(sb.toString());
    }

    public static Map<String, String> newMap() {
        return new LinkedHashMap<>();
    }
}
