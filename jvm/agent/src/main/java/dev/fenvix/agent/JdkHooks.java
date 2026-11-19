package dev.fenvix.agent;

import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Hooks inside a few JDK methods (retransformed at start-up). They cover calls
 * made by any code, the JDK included: SecureRandom (and so UUID.randomUUID and
 * every SecureRandom instance), directory listings, file opens and probes
 * (skip-with-proof capture), classpath resources, socket connects and DNS.
 * Only method bodies change (no new members), as retransformation requires.
 */
final class JdkHooks implements ClassFileTransformer {
    static final String DET = "dev/fenvix/rt/Det";
    static final String DEPS = "dev/fenvix/rt/Deps";

    enum Kind {
        /** call Det.m(args) at entry (loads the given argument slots). */
        ENTRY,
        /** before every ARETURN: value -> Det.m(value, args) (or args, value). */
        EXIT_FILTER,
        /** SecureRandom.nextBytes: if Det.secureBytes(b) return. */
        SECURE_BYTES,
        /** SecureRandom.generateSeed: r = Det.secureSeed(n); if r != null return r. */
        SECURE_SEED,
        /** before every ARETURN: dup value, Deps.resource(name, value). */
        EXIT_PEEK,
        /** before every LRETURN / ARETURN: value -> Det.m(value). */
        EXIT_VALUE,
        /** at entry: long argument in slot -> Det.m(long) -> back into the slot. */
        ENTRY_LONG_ARG,
        /** before every ARETURN: dup value, Det.m(value, args) (returns void). */
        EXIT_PEEK_FIRST,
        /** before every ARETURN: value -> Det.m(value, args) (returns the replacement). */
        EXIT_FILTER_FIRST
    }

    static final class Hook {
        final String cls, method, desc, target, targetDesc;
        final Kind kind;
        final int[] slots; // argument local slots to load (ALOAD)
        final String targetOwner;

        Hook(String cls, String method, String desc, Kind kind, String targetOwner, String target, String targetDesc, int... slots) {
            this.cls = cls;
            this.method = method;
            this.desc = desc;
            this.kind = kind;
            this.targetOwner = targetOwner;
            this.target = target;
            this.targetDesc = targetDesc;
            this.slots = slots;
        }
    }

    static final List<Hook> HOOKS = new ArrayList<>();

    static void add(Hook h) {
        HOOKS.add(h);
    }

    static {
        // randomness
        add(new Hook("java/security/SecureRandom", "nextBytes", "([B)V", Kind.SECURE_BYTES, DET, "secureBytes", "([B)Z", 1));
        add(new Hook("java/security/SecureRandom", "generateSeed", "(I)[B", Kind.SECURE_SEED, DET, "secureSeed", "(I)[B", 1));
        // directory listings (sorted under --det, recorded)
        add(new Hook("java/io/File", "normalizedList", "()[Ljava/lang/String;", Kind.EXIT_FILTER, DET, "fsList",
                "(Ljava/io/File;[Ljava/lang/String;)[Ljava/lang/String;", 0));
        // JDK 11-16 have no File.normalizedList(): hook File.list() there (see transform)
        add(new Hook("java/io/File", "list", "()[Ljava/lang/String;", Kind.EXIT_FILTER, DET, "fsList",
                "(Ljava/io/File;[Ljava/lang/String;)[Ljava/lang/String;", 0));
        add(new Hook("sun/nio/fs/UnixFileSystemProvider", "newDirectoryStream",
                "(Ljava/nio/file/Path;Ljava/nio/file/DirectoryStream$Filter;)Ljava/nio/file/DirectoryStream;", Kind.EXIT_FILTER, DET,
                "fsDirStream", "(Ljava/nio/file/DirectoryStream;Ljava/nio/file/Path;)Ljava/nio/file/DirectoryStream;", 1));
        // file opens and probes (capture)
        add(new Hook("java/io/FileInputStream", "<init>", "(Ljava/io/File;)V", Kind.ENTRY, DET, "fsOpenIn", "(Ljava/io/File;)V", 1));
        add(new Hook("java/io/FileOutputStream", "<init>", "(Ljava/io/File;Z)V", Kind.ENTRY, DET, "fsOpenOut", "(Ljava/io/File;)V", 1));
        add(new Hook("java/io/RandomAccessFile", "<init>", "(Ljava/io/File;Ljava/lang/String;)V", Kind.ENTRY, DET, "fsOpenRaf",
                "(Ljava/io/File;Ljava/lang/String;)V", 1, 2));
        add(new Hook("sun/nio/fs/UnixFileSystemProvider", "newByteChannel",
                "(Ljava/nio/file/Path;Ljava/util/Set;[Ljava/nio/file/attribute/FileAttribute;)Ljava/nio/channels/SeekableByteChannel;",
                Kind.ENTRY, DET, "nioOpen", "(Ljava/nio/file/Path;Ljava/util/Set;)V", 1, 2));
        add(new Hook("sun/nio/fs/UnixFileSystemProvider", "newFileChannel",
                "(Ljava/nio/file/Path;Ljava/util/Set;[Ljava/nio/file/attribute/FileAttribute;)Ljava/nio/channels/FileChannel;",
                Kind.ENTRY, DET, "nioOpen", "(Ljava/nio/file/Path;Ljava/util/Set;)V", 1, 2));
        add(new Hook("sun/nio/fs/UnixFileSystemProvider", "checkAccess", "(Ljava/nio/file/Path;[Ljava/nio/file/AccessMode;)V",
                Kind.ENTRY, DET, "nioProbe", "(Ljava/nio/file/Path;)V", 1));
        add(new Hook("sun/nio/fs/UnixFileSystemProvider", "readAttributes",
                "(Ljava/nio/file/Path;Ljava/lang/Class;[Ljava/nio/file/LinkOption;)Ljava/nio/file/attribute/BasicFileAttributes;",
                Kind.ENTRY, DET, "nioProbe", "(Ljava/nio/file/Path;)V", 1));
        add(new Hook("sun/nio/fs/UnixFileSystemProvider", "exists", "(Ljava/nio/file/Path;[Ljava/nio/file/LinkOption;)Z",
                Kind.ENTRY, DET, "nioProbe", "(Ljava/nio/file/Path;)V", 1));
        add(new Hook("sun/nio/fs/UnixFileSystemProvider", "readAttributesIfExists",
                "(Ljava/nio/file/Path;Ljava/lang/Class;[Ljava/nio/file/LinkOption;)Ljava/nio/file/attribute/BasicFileAttributes;",
                Kind.ENTRY, DET, "nioProbe", "(Ljava/nio/file/Path;)V", 1));
        add(new Hook("java/io/UnixFileSystem", "getBooleanAttributes", "(Ljava/io/File;)I", Kind.ENTRY, DET, "fsProbe",
                "(Ljava/io/File;)V", 1));
        // classpath resources (capture): found or not, and every location of getResources (ServiceLoader)
        add(new Hook("java/lang/ClassLoader", "getResource", "(Ljava/lang/String;)Ljava/net/URL;", Kind.EXIT_PEEK_FIRST, DEPS, "resource",
                "(Ljava/net/URL;Ljava/lang/ClassLoader;Ljava/lang/String;)V", 0, 1));
        add(new Hook("java/lang/ClassLoader", "getResources", "(Ljava/lang/String;)Ljava/util/Enumeration;", Kind.EXIT_FILTER_FIRST, DEPS,
                "resources", "(Ljava/util/Enumeration;Ljava/lang/ClassLoader;Ljava/lang/String;)Ljava/util/Enumeration;", 0, 1));
        // class lookups by name, found or not (capture)
        add(new Hook("java/lang/Class", "forName", "(Ljava/lang/String;)Ljava/lang/Class;", Kind.ENTRY, DEPS, "classLookup",
                "(Ljava/lang/String;)V", 0));
        add(new Hook("java/lang/Class", "forName", "(Ljava/lang/String;ZLjava/lang/ClassLoader;)Ljava/lang/Class;", Kind.ENTRY, DEPS,
                "classLookup", "(Ljava/lang/String;)V", 0));
        add(new Hook("java/lang/ClassLoader", "loadClass", "(Ljava/lang/String;)Ljava/lang/Class;", Kind.ENTRY, DEPS, "classLookup",
                "(Ljava/lang/String;)V", 1));
        // reflective metadata (capture): the class whose annotations, members or signature are read
        for (String[] m : new String[][] {
            {"getAnnotations", "()[Ljava/lang/annotation/Annotation;"},
            {"getDeclaredAnnotations", "()[Ljava/lang/annotation/Annotation;"},
            {"getDeclaredFields", "()[Ljava/lang/reflect/Field;"},
            {"getFields", "()[Ljava/lang/reflect/Field;"},
            {"getDeclaredField", "(Ljava/lang/String;)Ljava/lang/reflect/Field;"},
            {"getField", "(Ljava/lang/String;)Ljava/lang/reflect/Field;"},
            {"getDeclaredMethods", "()[Ljava/lang/reflect/Method;"},
            {"getMethods", "()[Ljava/lang/reflect/Method;"},
            {"getDeclaredMethod", "(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;"},
            {"getMethod", "(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;"},
            {"getDeclaredConstructors", "()[Ljava/lang/reflect/Constructor;"},
            {"getConstructors", "()[Ljava/lang/reflect/Constructor;"},
            {"getDeclaredConstructor", "([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;"},
            {"getConstructor", "([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;"},
            {"getGenericSuperclass", "()Ljava/lang/reflect/Type;"},
            {"getGenericInterfaces", "()[Ljava/lang/reflect/Type;"},
            {"getTypeParameters", "()[Ljava/lang/reflect/TypeVariable;"},
            {"getRecordComponents", "()[Ljava/lang/reflect/RecordComponent;"},
            {"getDeclaredClasses", "()[Ljava/lang/Class;"},
            {"getClasses", "()[Ljava/lang/Class;"},
            {"getInterfaces", "()[Ljava/lang/Class;"},
            {"getEnclosingMethod", "()Ljava/lang/reflect/Method;"},
        }) {
            add(new Hook("java/lang/Class", m[0], m[1], Kind.ENTRY, DEPS, "reflected", "(Ljava/lang/Class;)V", 0));
        }
        for (String[] m : new String[][] {
            {"getAnnotation", "(Ljava/lang/Class;)Ljava/lang/annotation/Annotation;"},
            {"isAnnotationPresent", "(Ljava/lang/Class;)Z"},
            {"getAnnotationsByType", "(Ljava/lang/Class;)[Ljava/lang/annotation/Annotation;"},
            {"getDeclaredAnnotation", "(Ljava/lang/Class;)Ljava/lang/annotation/Annotation;"},
            {"getDeclaredAnnotationsByType", "(Ljava/lang/Class;)[Ljava/lang/annotation/Annotation;"},
        }) {
            add(new Hook("java/lang/Class", m[0], m[1], Kind.ENTRY, DEPS, "reflected2", "(Ljava/lang/Class;Ljava/lang/Class;)V", 0, 1));
        }
        // annotation types parsed for a class or for the members of a class (their default values)
        add(new Hook("sun/reflect/annotation/AnnotationParser", "parseAnnotations",
                "([BLjdk/internal/reflect/ConstantPool;Ljava/lang/Class;)Ljava/util/Map;", Kind.EXIT_PEEK_FIRST, DEPS,
                "annotationsParsed", "(Ljava/util/Map;Ljava/lang/Class;)V", 2));
        add(new Hook("sun/reflect/annotation/AnnotationParser", "parseAnnotations",
                "([BLsun/reflect/ConstantPool;Ljava/lang/Class;)Ljava/util/Map;", Kind.EXIT_PEEK_FIRST, DEPS,
                "annotationsParsed", "(Ljava/util/Map;Ljava/lang/Class;)V", 2));
        // reflective static field access (shared state)
        for (String[] m : new String[][] {{"get", "Ljava/lang/Object;"}, {"getBoolean", "Z"}, {"getByte", "B"}, {"getChar", "C"},
            {"getShort", "S"}, {"getInt", "I"}, {"getLong", "J"}, {"getFloat", "F"}, {"getDouble", "D"}}) {
            add(new Hook("java/lang/reflect/Field", m[0], "(Ljava/lang/Object;)" + m[1], Kind.ENTRY, DEPS, "fieldGet",
                    "(Ljava/lang/reflect/Field;)V", 0));
        }
        for (String[] m : new String[][] {{"set", "Ljava/lang/Object;"}, {"setBoolean", "Z"}, {"setByte", "B"}, {"setChar", "C"},
            {"setShort", "S"}, {"setInt", "I"}, {"setLong", "J"}, {"setFloat", "F"}, {"setDouble", "D"}}) {
            add(new Hook("java/lang/reflect/Field", m[0], "(Ljava/lang/Object;" + m[1] + ")V", Kind.ENTRY, DEPS, "fieldSet",
                    "(Ljava/lang/reflect/Field;)V", 0));
        }
        String lk = "java/lang/invoke/MethodHandles$Lookup";
        String mt = "Ljava/lang/invoke/MethodType;";
        String mh = "Ljava/lang/invoke/MethodHandle;";
        add(new Hook(lk, "findStatic", "(Ljava/lang/Class;Ljava/lang/String;" + mt + ")" + mh, Kind.ENTRY, DEPS, "lookupFind", "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findVirtual", "(Ljava/lang/Class;Ljava/lang/String;" + mt + ")" + mh, Kind.ENTRY, DEPS, "lookupFind", "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findConstructor", "(Ljava/lang/Class;" + mt + ")" + mh, Kind.ENTRY, DEPS, "lookupFind", "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findSpecial", "(Ljava/lang/Class;Ljava/lang/String;" + mt + "Ljava/lang/Class;)" + mh, Kind.ENTRY, DEPS, "lookupFind",
                "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findGetter", "(Ljava/lang/Class;Ljava/lang/String;Ljava/lang/Class;)" + mh, Kind.ENTRY, DEPS, "lookupFind",
                "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findSetter", "(Ljava/lang/Class;Ljava/lang/String;Ljava/lang/Class;)" + mh, Kind.ENTRY, DEPS, "lookupFind",
                "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findStaticGetter", "(Ljava/lang/Class;Ljava/lang/String;Ljava/lang/Class;)" + mh, Kind.ENTRY, DEPS, "lookupStatic",
                "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findStaticSetter", "(Ljava/lang/Class;Ljava/lang/String;Ljava/lang/Class;)" + mh, Kind.ENTRY, DEPS, "lookupStatic",
                "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findStaticVarHandle", "(Ljava/lang/Class;Ljava/lang/String;Ljava/lang/Class;)Ljava/lang/invoke/VarHandle;", Kind.ENTRY,
                DEPS, "lookupStatic", "(Ljava/lang/Class;)V", 1));
        add(new Hook(lk, "findVarHandle", "(Ljava/lang/Class;Ljava/lang/String;Ljava/lang/Class;)Ljava/lang/invoke/VarHandle;", Kind.ENTRY,
                DEPS, "lookupFind", "(Ljava/lang/Class;)V", 1));
        // system properties written at run time (JVM-global state)
        add(new Hook("java/lang/System", "setProperty", "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;", Kind.ENTRY, DEPS,
                "propWrite", "(Ljava/lang/String;)V", 0));
        add(new Hook("java/lang/System", "clearProperty", "(Ljava/lang/String;)Ljava/lang/String;", Kind.ENTRY, DEPS, "propWrite",
                "(Ljava/lang/String;)V", 0));
        add(new Hook("java/lang/System", "setProperties", "(Ljava/util/Properties;)V", Kind.ENTRY, DEPS, "propWriteAll",
                "(Ljava/util/Properties;)V", 0));
        // inputs the capture cannot see: child processes, native libraries of the project
        add(new Hook("java/lang/ProcessBuilder", "start", "()Ljava/lang/Process;", Kind.ENTRY, DET, "procStart",
                "(Ljava/lang/ProcessBuilder;)V", 0));
        add(new Hook("java/lang/Runtime", "load0", "(Ljava/lang/Class;Ljava/lang/String;)V", Kind.ENTRY, DET, "nativeLoad",
                "(Ljava/lang/Class;Ljava/lang/String;)V", 1, 2));
        add(new Hook("java/lang/Runtime", "loadLibrary0", "(Ljava/lang/Class;Ljava/lang/String;)V", Kind.ENTRY, DET, "nativeLoad",
                "(Ljava/lang/Class;Ljava/lang/String;)V", 1, 2));
        // file timestamps on the virtual clock (code under test only)
        add(new Hook("java/io/File", "lastModified", "()J", Kind.EXIT_VALUE, DET, "mtimeFromReal", "(J)J"));
        add(new Hook("java/io/File", "setLastModified", "(J)Z", Kind.ENTRY_LONG_ARG, DET, "mtimeToReal", "(J)J", 1));
        add(new Hook("sun/nio/fs/UnixFileAttributes", "lastModifiedTime", "()Ljava/nio/file/attribute/FileTime;", Kind.EXIT_VALUE, DET,
                "fileTimeFromReal", "(Ljava/nio/file/attribute/FileTime;)Ljava/nio/file/attribute/FileTime;"));
        add(new Hook("sun/nio/fs/UnixFileAttributes", "lastAccessTime", "()Ljava/nio/file/attribute/FileTime;", Kind.EXIT_VALUE, DET,
                "fileTimeFromReal", "(Ljava/nio/file/attribute/FileTime;)Ljava/nio/file/attribute/FileTime;"));
        add(new Hook("sun/nio/fs/UnixFileAttributes", "creationTime", "()Ljava/nio/file/attribute/FileTime;", Kind.EXIT_VALUE, DET,
                "fileTimeFromReal", "(Ljava/nio/file/attribute/FileTime;)Ljava/nio/file/attribute/FileTime;"));
        // network
        add(new Hook("java/net/Socket", "connect", "(Ljava/net/SocketAddress;I)V", Kind.ENTRY, DET, "netConnect",
                "(Ljava/net/SocketAddress;)V", 1));
        add(new Hook("sun/nio/ch/SocketChannelImpl", "connect", "(Ljava/net/SocketAddress;)Z", Kind.ENTRY, DET, "netConnect",
                "(Ljava/net/SocketAddress;)V", 1));
        add(new Hook("java/net/InetAddress", "getAllByName", "(Ljava/lang/String;)[Ljava/net/InetAddress;", Kind.ENTRY, DET, "dnsLookup",
                "(Ljava/lang/String;)V", 0));
        add(new Hook("java/net/InetAddress", "getByName", "(Ljava/lang/String;)Ljava/net/InetAddress;", Kind.ENTRY, DET, "dnsLookup",
                "(Ljava/lang/String;)V", 0));
    }

    static List<String> targets() {
        List<String> t = new ArrayList<>();
        for (Hook h : HOOKS) {
            String n = h.cls.replace('/', '.');
            if (!t.contains(n)) t.add(n);
        }
        return t;
    }

    private final Map<String, Boolean> done = Collections.synchronizedMap(new LinkedHashMap<>());

    List<String> installed() {
        List<String> l = new ArrayList<>();
        synchronized (done) {
            for (Map.Entry<String, Boolean> e : done.entrySet()) if (e.getValue()) l.add(e.getKey());
        }
        return l;
    }

    @Override
    public byte[] transform(ClassLoader loader, String name, Class<?> redefined, ProtectionDomain pd, byte[] bytes) {
        if (loader != null || name == null) return null;
        List<Hook> mine = new ArrayList<>();
        for (Hook h : HOOKS) if (h.cls.equals(name)) mine.add(h);
        if (mine.isEmpty()) return null;
        if (name.equals("java/io/File")) {
            boolean hasNormalized = new String(bytes, java.nio.charset.StandardCharsets.ISO_8859_1).contains("normalizedList");
            mine.removeIf(h -> hasNormalized ? h.method.equals("list") : h.method.equals("normalizedList"));
        }
        try {
            ClassReader cr = new ClassReader(bytes);
            ClassWriter cw = new ClassWriter(cr, ClassWriter.COMPUTE_MAXS);
            cr.accept(new ClassVisitor(Opcodes.ASM9, cw) {
                @Override
                public MethodVisitor visitMethod(int access, String m, String desc, String sig, String[] exc) {
                    MethodVisitor mv = super.visitMethod(access, m, desc, sig, exc);
                    for (Hook h : mine) {
                        if (h.method.equals(m) && h.desc.equals(desc) && (access & Opcodes.ACC_NATIVE) == 0) {
                            done.put(h.cls.substring(h.cls.lastIndexOf('/') + 1) + "." + m, Boolean.TRUE);
                            return new HookVisitor(mv, h);
                        }
                    }
                    return mv;
                }
            }, 0);
            return cw.toByteArray();
        } catch (Throwable t) {
            System.err.println("fenvix: JDK hook on " + name + " failed: " + t);
            return null;
        }
    }

    static final class HookVisitor extends MethodVisitor {
        final Hook h;

        HookVisitor(MethodVisitor mv, Hook h) {
            super(Opcodes.ASM9, mv);
            this.h = h;
        }

        @Override
        public void visitCode() {
            super.visitCode();
            switch (h.kind) {
                case ENTRY:
                    for (int s : h.slots) super.visitVarInsn(Opcodes.ALOAD, s);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
                    break;
                case ENTRY_LONG_ARG:
                    super.visitVarInsn(Opcodes.LLOAD, h.slots[0]);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
                    super.visitVarInsn(Opcodes.LSTORE, h.slots[0]);
                    break;
                case SECURE_BYTES: {
                    Label go = new Label();
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
                    super.visitJumpInsn(Opcodes.IFEQ, go);
                    super.visitInsn(Opcodes.RETURN);
                    super.visitLabel(go);
                    super.visitFrame(Opcodes.F_SAME, 0, null, 0, null);
                    break;
                }
                case SECURE_SEED: {
                    Label go = new Label();
                    super.visitVarInsn(Opcodes.ILOAD, 1);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
                    super.visitInsn(Opcodes.DUP);
                    super.visitJumpInsn(Opcodes.IFNULL, go);
                    super.visitInsn(Opcodes.ARETURN);
                    super.visitLabel(go);
                    super.visitFrame(Opcodes.F_SAME1, 0, null, 1, new Object[] {"[B"});
                    super.visitInsn(Opcodes.POP);
                    break;
                }
                default:
                    break;
            }
        }

        @Override
        public void visitInsn(int op) {
            if (h.kind == Kind.EXIT_VALUE && (op == Opcodes.LRETURN || op == Opcodes.ARETURN)) {
                super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
                super.visitInsn(op);
                return;
            }
            if (op == Opcodes.ARETURN && h.kind == Kind.EXIT_PEEK_FIRST) {
                super.visitInsn(Opcodes.DUP);
                for (int s : h.slots) super.visitVarInsn(Opcodes.ALOAD, s);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
            } else if (op == Opcodes.ARETURN && h.kind == Kind.EXIT_FILTER_FIRST) {
                for (int s : h.slots) super.visitVarInsn(Opcodes.ALOAD, s);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
            } else if (op == Opcodes.ARETURN) {
                if (h.kind == Kind.EXIT_FILTER) {
                    if (h.targetDesc.startsWith("(Ljava/io/File;")) {
                        // (this, value): value is on the stack
                        super.visitVarInsn(Opcodes.ALOAD, h.slots[0]);
                        super.visitInsn(Opcodes.SWAP);
                    } else {
                        // (value, arg)
                        super.visitVarInsn(Opcodes.ALOAD, h.slots[0]);
                    }
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
                } else if (h.kind == Kind.EXIT_PEEK) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, h.slots[0]);
                    super.visitInsn(Opcodes.SWAP);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, h.targetOwner, h.target, h.targetDesc, false);
                }
            }
            super.visitInsn(op);
        }
    }
}
