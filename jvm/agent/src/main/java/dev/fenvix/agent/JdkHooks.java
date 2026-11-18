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
        EXIT_PEEK
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
        // classpath resources (capture)
        add(new Hook("java/lang/ClassLoader", "getResource", "(Ljava/lang/String;)Ljava/net/URL;", Kind.EXIT_PEEK, DEPS, "resource",
                "(Ljava/lang/String;Ljava/net/URL;)V", 1));
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
            if (op == Opcodes.ARETURN) {
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
