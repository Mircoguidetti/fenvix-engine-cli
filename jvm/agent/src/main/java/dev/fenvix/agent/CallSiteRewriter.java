package dev.fenvix.agent;

import dev.fenvix.rt.Deps;
import dev.fenvix.rt.Det;
import dev.fenvix.rt.Infra;
import dev.fenvix.rt.Native;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import java.util.HashMap;
import java.util.Map;

/**
 * Rewrites call sites in code under test (every class not loaded by the
 * bootstrap or platform loader and not in {@link Infra}) so that the sources of
 * non-determinism go through {@link Det}. Each rewritten call passes its own
 * call site ({@code pkg/File.java:line}, known at rewrite time) as an extra
 * argument, so no stack walk is needed to name the site of an event.
 *
 * <p>With the skip-with-proof capture on, it also inserts a probe at the start of
 * every method (class coverage per test) and before every static field access
 * to a non-JDK class, and digests the class-file bytes.
 */
final class CallSiteRewriter implements ClassFileTransformer {
    static final String DET = "dev/fenvix/rt/Det";
    static final String S = "Ljava/lang/String;";

    /** owner.name+desc -> Det method (static; descriptor = original args [+ receiver] + String site). */
    static final Map<String, String[]> STATIC = new HashMap<>();
    /** name+desc of virtual/interface timed waits on JDK concurrency owners. */
    static final Map<String, String[]> VIRTUAL = new HashMap<>();
    static final String[] NOW_CLASSES = {"java/time/LocalDateTime", "java/time/LocalDate", "java/time/LocalTime",
        "java/time/ZonedDateTime", "java/time/OffsetDateTime", "java/time/OffsetTime", "java/time/Year",
        "java/time/YearMonth", "java/time/MonthDay"};

    static void st(String key, String m, String desc) {
        STATIC.put(key, new String[] {m, desc});
    }

    static {
        // time
        st("java/lang/System.currentTimeMillis()J", "currentTimeMillis", "(" + S + ")J");
        st("java/lang/System.nanoTime()J", "nanoTime", "(" + S + ")J");
        st("java/time/Instant.now()Ljava/time/Instant;", "instantNow", "(" + S + ")Ljava/time/Instant;");
        st("java/time/Clock.systemUTC()Ljava/time/Clock;", "clockUTC", "(" + S + ")Ljava/time/Clock;");
        st("java/time/Clock.systemDefaultZone()Ljava/time/Clock;", "clockDefaultZone", "(" + S + ")Ljava/time/Clock;");
        st("java/time/Clock.system(Ljava/time/ZoneId;)Ljava/time/Clock;", "clockSystem", "(Ljava/time/ZoneId;" + S + ")Ljava/time/Clock;");
        st("java/util/Calendar.getInstance()Ljava/util/Calendar;", "calendarGetInstance", "(" + S + ")Ljava/util/Calendar;");
        st("java/util/Calendar.getInstance(Ljava/util/TimeZone;)Ljava/util/Calendar;", "calendarGetInstanceTz", "(Ljava/util/TimeZone;" + S + ")Ljava/util/Calendar;");
        st("java/util/Calendar.getInstance(Ljava/util/Locale;)Ljava/util/Calendar;", "calendarGetInstanceLocale", "(Ljava/util/Locale;" + S + ")Ljava/util/Calendar;");
        st("java/util/Calendar.getInstance(Ljava/util/TimeZone;Ljava/util/Locale;)Ljava/util/Calendar;", "calendarGetInstanceTzLocale", "(Ljava/util/TimeZone;Ljava/util/Locale;" + S + ")Ljava/util/Calendar;");
        st("java/lang/Thread.sleep(J)V", "sleep", "(J" + S + ")V");
        st("java/lang/Thread.sleep(JI)V", "sleep2", "(JI" + S + ")V");
        st("java/lang/Thread.sleep(Ljava/time/Duration;)V", "sleepDuration", "(Ljava/time/Duration;" + S + ")V");
        st("java/util/concurrent/locks/LockSupport.parkNanos(J)V", "parkNanos", "(J" + S + ")V");
        st("java/util/concurrent/locks/LockSupport.parkNanos(Ljava/lang/Object;J)V", "parkNanosBlocker", "(Ljava/lang/Object;J" + S + ")V");
        st("java/util/concurrent/Executors.newScheduledThreadPool(I)Ljava/util/concurrent/ScheduledExecutorService;", "newScheduledThreadPool", "(I" + S + ")Ljava/util/concurrent/ScheduledExecutorService;");
        st("java/util/concurrent/Executors.newScheduledThreadPool(ILjava/util/concurrent/ThreadFactory;)Ljava/util/concurrent/ScheduledExecutorService;", "newScheduledThreadPoolTf", "(ILjava/util/concurrent/ThreadFactory;" + S + ")Ljava/util/concurrent/ScheduledExecutorService;");
        st("java/util/concurrent/Executors.newSingleThreadScheduledExecutor()Ljava/util/concurrent/ScheduledExecutorService;", "newSingleThreadScheduledExecutor", "(" + S + ")Ljava/util/concurrent/ScheduledExecutorService;");
        st("java/util/concurrent/Executors.newSingleThreadScheduledExecutor(Ljava/util/concurrent/ThreadFactory;)Ljava/util/concurrent/ScheduledExecutorService;", "newSingleThreadScheduledExecutorTf", "(Ljava/util/concurrent/ThreadFactory;" + S + ")Ljava/util/concurrent/ScheduledExecutorService;");
        // randomness
        st("java/lang/Math.random()D", "mathRandom", "(" + S + ")D");
        st("java/lang/StrictMath.random()D", "mathRandom", "(" + S + ")D");
        st("java/util/UUID.randomUUID()Ljava/util/UUID;", "randomUUID", "(" + S + ")Ljava/util/UUID;");
        st("java/util/concurrent/ThreadLocalRandom.current()Ljava/util/concurrent/ThreadLocalRandom;", "tlrCurrent", "(" + S + ")Ljava/util/concurrent/ThreadLocalRandom;");
        st("java/util/Collections.shuffle(Ljava/util/List;)V", "collectionsShuffle", "(Ljava/util/List;" + S + ")V");
        // environment and system properties (skip-with-proof capture)
        st("java/lang/System.getenv(Ljava/lang/String;)Ljava/lang/String;", "getenv", "(" + S + S + ")" + S);
        st("java/lang/System.getenv()Ljava/util/Map;", "getenvAll", "(" + S + ")Ljava/util/Map;");
        st("java/lang/System.getProperty(Ljava/lang/String;)Ljava/lang/String;", "getProperty", "(" + S + S + ")" + S);
        st("java/lang/System.getProperty(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;", "getProperty2", "(" + S + S + S + ")" + S);
        st("java/lang/System.getProperties()Ljava/util/Properties;", "getProperties", "(" + S + ")Ljava/util/Properties;");
        st("java/lang/Integer.getInteger(Ljava/lang/String;)Ljava/lang/Integer;", "getInteger", "(" + S + S + ")Ljava/lang/Integer;");
        st("java/lang/Integer.getInteger(Ljava/lang/String;I)Ljava/lang/Integer;", "getInteger2", "(" + S + "I" + S + ")Ljava/lang/Integer;");
        st("java/lang/Integer.getInteger(Ljava/lang/String;Ljava/lang/Integer;)Ljava/lang/Integer;", "getInteger3", "(" + S + "Ljava/lang/Integer;" + S + ")Ljava/lang/Integer;");
        st("java/lang/Long.getLong(Ljava/lang/String;)Ljava/lang/Long;", "getLong", "(" + S + S + ")Ljava/lang/Long;");
        st("java/lang/Long.getLong(Ljava/lang/String;J)Ljava/lang/Long;", "getLong2", "(" + S + "J" + S + ")Ljava/lang/Long;");
        st("java/lang/Long.getLong(Ljava/lang/String;Ljava/lang/Long;)Ljava/lang/Long;", "getLong3", "(" + S + "Ljava/lang/Long;" + S + ")Ljava/lang/Long;");
        st("java/lang/Boolean.getBoolean(Ljava/lang/String;)Z", "getBoolean", "(" + S + S + ")Z");

        // virtual / interface calls: receiver becomes the first argument
        VIRTUAL.put("sleep(J)V@java/util/concurrent/TimeUnit", new String[] {"timeUnitSleep", "(Ljava/util/concurrent/TimeUnit;J" + S + ")V"});
        VIRTUAL.put("wait(J)V@*", new String[] {"objectWait", "(Ljava/lang/Object;J" + S + ")V"});
        VIRTUAL.put("join(J)V@java/lang/Thread", new String[] {"threadJoin", "(Ljava/lang/Thread;J" + S + ")V"});
        VIRTUAL.put("await(JLjava/util/concurrent/TimeUnit;)Z@java/util/concurrent/CountDownLatch",
                new String[] {"latchAwait", "(Ljava/util/concurrent/CountDownLatch;JLjava/util/concurrent/TimeUnit;" + S + ")Z"});
        VIRTUAL.put("await(JLjava/util/concurrent/TimeUnit;)Z@java/util/concurrent/locks/Condition",
                new String[] {"conditionAwait", "(Ljava/util/concurrent/locks/Condition;JLjava/util/concurrent/TimeUnit;" + S + ")Z"});
        VIRTUAL.put("awaitNanos(J)J@java/util/concurrent/locks/Condition",
                new String[] {"conditionAwaitNanos", "(Ljava/util/concurrent/locks/Condition;J" + S + ")J"});
        VIRTUAL.put("get(JLjava/util/concurrent/TimeUnit;)Ljava/lang/Object;@future",
                new String[] {"futureGet", "(Ljava/util/concurrent/Future;JLjava/util/concurrent/TimeUnit;" + S + ")Ljava/lang/Object;"});
        VIRTUAL.put("poll(JLjava/util/concurrent/TimeUnit;)Ljava/lang/Object;@queue",
                new String[] {"queuePoll", "(Ljava/util/concurrent/BlockingQueue;JLjava/util/concurrent/TimeUnit;" + S + ")Ljava/lang/Object;"});
        VIRTUAL.put("awaitTermination(JLjava/util/concurrent/TimeUnit;)Z@executor",
                new String[] {"awaitTermination", "(Ljava/util/concurrent/ExecutorService;JLjava/util/concurrent/TimeUnit;" + S + ")Z"});
    }

    static final String[] FUTURES = {"java/util/concurrent/Future", "java/util/concurrent/CompletableFuture",
        "java/util/concurrent/FutureTask", "java/util/concurrent/ScheduledFuture", "java/util/concurrent/RunnableFuture",
        "java/util/concurrent/ForkJoinTask"};
    static final String[] QUEUES = {"java/util/concurrent/BlockingQueue", "java/util/concurrent/LinkedBlockingQueue",
        "java/util/concurrent/ArrayBlockingQueue", "java/util/concurrent/LinkedBlockingDeque", "java/util/concurrent/BlockingDeque",
        "java/util/concurrent/PriorityBlockingQueue", "java/util/concurrent/SynchronousQueue", "java/util/concurrent/DelayQueue",
        "java/util/concurrent/LinkedTransferQueue", "java/util/concurrent/TransferQueue"};
    static final String[] EXECUTORS = {"java/util/concurrent/ExecutorService", "java/util/concurrent/ThreadPoolExecutor",
        "java/util/concurrent/ScheduledExecutorService", "java/util/concurrent/ScheduledThreadPoolExecutor",
        "java/util/concurrent/ForkJoinPool"};

    static boolean in(String[] a, String s) {
        for (String x : a) if (x.equals(s)) return true;
        return false;
    }

    static String[] virtualRule(String owner, String name, String desc) {
        String nd = name + desc;
        if (nd.equals("wait(J)V")) return VIRTUAL.get("wait(J)V@*");
        String[] r = VIRTUAL.get(nd + "@" + owner);
        if (r != null) return r;
        if (nd.equals("get(JLjava/util/concurrent/TimeUnit;)Ljava/lang/Object;") && in(FUTURES, owner)) return VIRTUAL.get(nd + "@future");
        if (nd.equals("poll(JLjava/util/concurrent/TimeUnit;)Ljava/lang/Object;") && in(QUEUES, owner)) return VIRTUAL.get(nd + "@queue");
        if (nd.equals("awaitTermination(JLjava/util/concurrent/TimeUnit;)Z") && in(EXECUTORS, owner)) return VIRTUAL.get(nd + "@executor");
        if (owner.equals("java/util/concurrent/locks/ReentrantLock$ConditionObject")
                || owner.equals("java/util/concurrent/locks/AbstractQueuedSynchronizer$ConditionObject")) {
            return VIRTUAL.get(nd + "@java/util/concurrent/locks/Condition");
        }
        return null;
    }

    static boolean jdkOwner(String owner) {
        return owner.startsWith("java/") || owner.startsWith("javax/") || owner.startsWith("jdk/") || owner.startsWith("sun/")
                || owner.startsWith("com/sun/") || owner.startsWith("[");
    }

    @Override
    public byte[] transform(ClassLoader loader, String name, Class<?> redefined, ProtectionDomain pd, byte[] bytes) {
        if (name == null || loader == null || redefined != null) return null;
        if (loader == ClassLoader.getPlatformClassLoader()) return null;
        if (Infra.isInfra(name) || name.equals("module-info") || name.startsWith("dev/fenvix/")) return null;
        try {
            String src = "";
            if (pd != null && pd.getCodeSource() != null && pd.getCodeSource().getLocation() != null) {
                String loc = pd.getCodeSource().getLocation().getPath();
                if (Infra.isToolDistribution(loc)) return null; // the build tool's own libraries (Gradle worker)
            }
            if (Det.DEPS) {
                if (pd != null && pd.getCodeSource() != null && pd.getCodeSource().getLocation() != null) {
                    try {
                        src = new java.io.File(pd.getCodeSource().getLocation().toURI()).getPath();
                    } catch (Exception e) {
                        src = pd.getCodeSource().getLocation().toString();
                    }
                }
                // classes without a code source are generated at run time (proxies, mocks): their
                // definition derives from other classes, they are not part of the key
                if (!src.isEmpty()) Deps.classDefined(name, Native.digest(bytes), src);
            }
            ClassReader cr = new ClassReader(bytes);
            ClassWriter cw = new ClassWriter(cr, ClassWriter.COMPUTE_MAXS);
            Rewriter rw = new Rewriter(cw, name);
            cr.accept(rw, 0);
            if (!rw.changed) return null;
            return cw.toByteArray();
        } catch (Throwable t) {
            if (Boolean.getBoolean("fenvix.debug")) {
                System.err.println("fenvix: not rewritten " + name + ": " + t);
            }
            return null;
        }
    }

    static final class Rewriter extends ClassVisitor {
        final String cls;
        String sourceBase;
        boolean changed;
        final int classId;

        Rewriter(ClassVisitor cv, String cls) {
            super(Opcodes.ASM9, cv);
            this.cls = cls;
            int slash = cls.lastIndexOf('/');
            String simple = cls.substring(slash + 1);
            int dollar = simple.indexOf('$');
            if (dollar > 0) simple = simple.substring(0, dollar);
            this.sourceBase = (slash >= 0 ? cls.substring(0, slash + 1) : "") + simple + ".java";
            this.classId = Det.DEPS ? Deps.classId(cls) : -1;
        }

        @Override
        public void visitSource(String source, String debug) {
            if (source != null) {
                int slash = cls.lastIndexOf('/');
                sourceBase = (slash >= 0 ? cls.substring(0, slash + 1) : "") + source;
            }
            super.visitSource(source, debug);
        }

        @Override
        public MethodVisitor visitMethod(int access, String name, String desc, String sig, String[] exc) {
            MethodVisitor mv = super.visitMethod(access, name, desc, sig, exc);
            if ((access & (Opcodes.ACC_ABSTRACT | Opcodes.ACC_NATIVE)) != 0) return mv;
            return new MethodRewriter(mv, this, name);
        }
    }

    static final class MethodRewriter extends MethodVisitor {
        final Rewriter owner;
        final String method;
        int line;
        boolean probed;

        MethodRewriter(MethodVisitor mv, Rewriter owner, String method) {
            super(Opcodes.ASM9, mv);
            this.owner = owner;
            this.method = method;
        }

        String site() {
            return owner.sourceBase + ":" + line;
        }

        @Override
        public void visitCode() {
            super.visitCode();
            if (Det.DEPS && owner.classId >= 0) {
                push(owner.classId);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, DET, "touch", "(I)V", false);
                owner.changed = true;
            }
        }

        void push(int v) {
            if (v <= Short.MAX_VALUE) super.visitIntInsn(Opcodes.SIPUSH, v);
            else super.visitLdcInsn(v);
        }

        @Override
        public void visitLineNumber(int l, Label start) {
            line = l;
            super.visitLineNumber(l, start);
        }

        @Override
        public void visitFieldInsn(int op, String fowner, String name, String desc) {
            if (Det.DEPS && (op == Opcodes.GETSTATIC || op == Opcodes.PUTSTATIC) && !jdkOwner(fowner) && !Infra.isInfra(fowner)) {
                boolean clinitSelf = method.equals("<clinit>") && fowner.equals(owner.cls);
                if (!clinitSelf) {
                    push(Deps.classId(fowner));
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, DET, op == Opcodes.GETSTATIC ? "touchStatic" : "writeStatic", "(I)V", false);
                    owner.changed = true;
                }
            }
            super.visitFieldInsn(op, fowner, name, desc);
        }

        @Override
        public void visitMethodInsn(int op, String mowner, String name, String desc, boolean itf) {
            if (op == Opcodes.INVOKESTATIC) {
                String[] r = STATIC.get(mowner + "." + name + desc);
                if (r != null) {
                    super.visitLdcInsn(site());
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, DET, r[0], r[1], false);
                    owner.changed = true;
                    return;
                }
                if (name.equals("now") && in(NOW_CLASSES, mowner)) {
                    if (desc.equals("()L" + mowner + ";")) {
                        super.visitLdcInsn(site());
                        super.visitMethodInsn(Opcodes.INVOKESTATIC, DET, "clockDefaultZone", "(" + S + ")Ljava/time/Clock;", false);
                        super.visitMethodInsn(Opcodes.INVOKESTATIC, mowner, "now", "(Ljava/time/Clock;)L" + mowner + ";", false);
                        owner.changed = true;
                        return;
                    }
                    if (desc.equals("(Ljava/time/ZoneId;)L" + mowner + ";")) {
                        super.visitLdcInsn(site());
                        super.visitMethodInsn(Opcodes.INVOKESTATIC, DET, "clockSystem", "(Ljava/time/ZoneId;" + S + ")Ljava/time/Clock;", false);
                        super.visitMethodInsn(Opcodes.INVOKESTATIC, mowner, "now", "(Ljava/time/Clock;)L" + mowner + ";", false);
                        owner.changed = true;
                        return;
                    }
                }
            } else if (op == Opcodes.INVOKESPECIAL && name.equals("<init>") && desc.equals("()V")) {
                String helper = null;
                if (mowner.equals("java/util/Date")) helper = "currentTimeMillis";
                else if (mowner.equals("java/util/Random") || mowner.equals("java/util/SplittableRandom")) helper = "newRandomSeed";
                if (helper != null) {
                    super.visitLdcInsn(site());
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, DET, helper, "(" + S + ")J", false);
                    super.visitMethodInsn(Opcodes.INVOKESPECIAL, mowner, "<init>", "(J)V", false);
                    owner.changed = true;
                    return;
                }
            } else if (op == Opcodes.INVOKEVIRTUAL || op == Opcodes.INVOKEINTERFACE) {
                String[] r = virtualRule(mowner, name, desc);
                if (r != null) {
                    super.visitLdcInsn(site());
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, DET, r[0], r[1], false);
                    // keep the static return type of the original call site
                    String origRet = desc.substring(desc.indexOf(')') + 1);
                    String newRet = r[1].substring(r[1].indexOf(')') + 1);
                    if (!origRet.equals(newRet) && origRet.startsWith("L")) {
                        super.visitTypeInsn(Opcodes.CHECKCAST, origRet.substring(1, origRet.length() - 1));
                    }
                    owner.changed = true;
                    return;
                }
            }
            super.visitMethodInsn(op, mowner, name, desc, itf);
        }
    }
}
