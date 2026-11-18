package dev.fenvix.agent;

import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/**
 * Hooks in the JUnit 4 runner (any JUnit 4 run: Surefire's junit4 provider,
 * Gradle's useJUnit(), JUnitCore):
 * <ul>
 *   <li>{@code RunNotifier.fire*Started}: attaches the fenvix run listener once per notifier (per-test brackets);
 *   <li>{@code ParentRunner.getFilteredChildren}: reproducible shuffle of the
 *       children (test methods, suite members) with a non-zero seed.
 * </ul>
 */
final class RunnerHooks implements ClassFileTransformer {
    static final String HOOK = "dev/fenvix/junit/Junit4Hook";

    @Override
    public byte[] transform(ClassLoader loader, String name, Class<?> redefined, ProtectionDomain pd, byte[] bytes) {
        if (!"org/junit/runner/notification/RunNotifier".equals(name) && !"org/junit/runners/ParentRunner".equals(name)) return null;
        try {
            ClassReader cr = new ClassReader(bytes);
            ClassWriter cw = new ClassWriter(cr, ClassWriter.COMPUTE_MAXS);
            boolean notifier = name.endsWith("RunNotifier");
            cr.accept(new ClassVisitor(Opcodes.ASM9, cw) {
                @Override
                public MethodVisitor visitMethod(int access, String m, String desc, String sig, String[] exc) {
                    MethodVisitor mv = super.visitMethod(access, m, desc, sig, exc);
                    if (notifier && (m.equals("fireTestRunStarted") || m.equals("fireTestSuiteStarted") || m.equals("fireTestStarted")
                            || m.equals("fireTestIgnored"))) {
                        // attach at the first event (not in the constructor: subclasses such as
                        // Surefire's Notifier keep listeners in fields initialised after super())
                        return new MethodVisitor(Opcodes.ASM9, mv) {
                            @Override
                            public void visitCode() {
                                super.visitCode();
                                super.visitVarInsn(Opcodes.ALOAD, 0);
                                super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOK, "attach", "(Ljava/lang/Object;)V", false);
                            }
                        };
                    }
                    if (!notifier && m.equals("getFilteredChildren") && desc.startsWith("()")) {
                        String ret = desc.substring(2);
                        return new MethodVisitor(Opcodes.ASM9, mv) {
                            @Override
                            public void visitInsn(int op) {
                                if (op == Opcodes.ARETURN) {
                                    super.visitVarInsn(Opcodes.ALOAD, 0);
                                    super.visitInsn(Opcodes.SWAP);
                                    super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOK, "order",
                                            "(Ljava/lang/Object;Ljava/util/Collection;)Ljava/util/Collection;", false);
                                    if (!ret.equals("Ljava/util/Collection;")) {
                                        super.visitTypeInsn(Opcodes.CHECKCAST, ret.substring(1, ret.length() - 1));
                                    }
                                }
                                super.visitInsn(op);
                            }
                        };
                    }
                    return mv;
                }
            }, 0);
            return cw.toByteArray();
        } catch (Throwable t) {
            System.err.println("fenvix: JUnit 4 hook on " + name + " failed: " + t);
            return null;
        }
    }
}
