package dev.fenvix.cli;

import java.io.File;
import java.lang.reflect.Method;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * {@code java -jar fenvix-agent.jar <command>}: the JVM shell's command line.
 *
 * <pre>
 * run [--det] [--det-seed=N] [--deps] [--det-disable=a,b] [--det-allow-host=h] [--out=DIR] -- &lt;gradle|gradlew|mvn|mvnw ...&gt;
 *     runs the build with the agent wired in (Gradle: init script; Maven: core extension),
 *     then merges the per-JVM trace parts into DIR/trace.jsonl (default DIR = .fenvix)
 * merge DIR             merge DIR/parts/*.jsonl into DIR/trace.jsonl
 * verify A.jsonl B.jsonl ...   compare traces (the same verifier as detpy and detjs)
 * paths                 print where the init script and the Maven extension were extracted
 * </pre>
 */
public final class Main {
    private Main() {}

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            usage();
            System.exit(2);
        }
        switch (args[0]) {
            case "run":
                System.exit(run(Arrays.copyOfRange(args, 1, args.length)));
                break;
            case "merge":
                System.out.println(merge(args.length > 1 ? args[1] : ".fenvix"));
                break;
            case "verify":
                if (args.length > 1 && args[1].equals("--json")) {
                    Class<?> n = nativeClass();
                    System.out.print((String) n.getMethod("verify", String[].class).invoke(null, (Object) Arrays.copyOfRange(args, 2, args.length)));
                } else {
                    System.out.print(verify(Arrays.copyOfRange(args, 1, args.length)));
                }
                break;
            case "paths": {
                Path d = assets();
                System.out.println("init-script " + d.resolve("fenvix.init.gradle"));
                System.out.println("maven-ext " + d.resolve("fenvix-maven-ext.jar"));
                System.out.println("agent " + self());
                break;
            }
            default:
                usage();
                System.exit(2);
        }
    }

    static void usage() {
        System.err.println("usage: fenvix-jvm run [--det] [--det-seed=N] [--deps] [--det-disable=a,b] [--det-allow-host=h] [--out=DIR] -- <build command>\n"
                + "       fenvix-jvm merge DIR | verify TRACE... | paths");
    }

    static String self() throws Exception {
        return new File(Main.class.getProtectionDomain().getCodeSource().getLocation().toURI()).getAbsolutePath();
    }

    static Path assets() throws Exception {
        Path dir = dev.fenvix.agent.Agent.extractAll();
        return dir;
    }

    static ClassLoader rtLoader() throws Exception {
        Path d = assets();
        return new URLClassLoader(new URL[] {d.resolve("fenvix-rt.jar").toUri().toURL()}, null);
    }

    static Class<?> nativeClass() throws Exception {
        ClassLoader l = rtLoader();
        Class<?> n = Class.forName("dev.fenvix.rt.Native", true, l);
        n.getMethod("load", String.class).invoke(null, assets().resolve("libfenvix_jvm.so").toString());
        return n;
    }

    static String verify(String[] paths) throws Exception {
        Class<?> n = nativeClass();
        Method m = n.getMethod("verifyText", String[].class, boolean.class);
        return (String) m.invoke(null, paths, false);
    }

    /** Merge the parts (named by start time) into DIR/trace.jsonl; returns the summary JSON. */
    static String merge(String dir) throws Exception {
        File[] parts = new File(dir, "parts").listFiles((d, n) -> n.endsWith(".jsonl"));
        if (parts == null || parts.length == 0) return "{\"n_tests\":0,\"parts\":0}";
        Arrays.sort(parts, (a, b) -> {
            long ta = Long.parseLong(a.getName().split("-")[0]);
            long tb = Long.parseLong(b.getName().split("-")[0]);
            return ta != tb ? Long.compare(ta, tb) : a.getName().compareTo(b.getName());
        });
        String[] ps = new String[parts.length];
        for (int i = 0; i < parts.length; i++) ps[i] = parts[i].getPath();
        String meta = firstMeta(parts[0]);
        Class<?> n = nativeClass();
        Method m = n.getMethod("mergeTraces", String[].class, String.class, String.class, String[].class);
        return (String) m.invoke(null, ps, new File(dir, "trace.jsonl").getPath(), meta, new String[0]);
    }

    /** The meta object of a part's header line (crude but dependency-free). */
    static String firstMeta(File part) throws Exception {
        String head = Files.readAllLines(part.toPath()).get(0);
        int i = head.indexOf("\"meta\":");
        if (i < 0) return "{}";
        int start = head.indexOf('{', i);
        int depth = 0;
        boolean str = false;
        for (int k = start; k < head.length(); k++) {
            char c = head.charAt(k);
            if (str) {
                if (c == '\\') k++;
                else if (c == '"') str = false;
            } else if (c == '"') str = true;
            else if (c == '{') depth++;
            else if (c == '}' && --depth == 0) return head.substring(start, k + 1);
        }
        return "{}";
    }

    static int run(String[] args) throws Exception {
        boolean det = false, deps = false;
        String seed = "0", disable = "", allow = "", out = null;
        int i = 0;
        for (; i < args.length; i++) {
            String a = args[i];
            if (a.equals("--")) {
                i++;
                break;
            } else if (a.equals("--det")) det = true;
            else if (a.equals("--deps")) deps = true;
            else if (a.startsWith("--det-seed=")) {
                seed = a.substring(11);
                det = true;
            } else if (a.startsWith("--det-disable=")) disable = a.substring(14);
            else if (a.startsWith("--det-allow-host=")) allow = allow.isEmpty() ? a.substring(17) : allow + "," + a.substring(17);
            else if (a.startsWith("--out=")) out = a.substring(6);
            else break;
        }
        List<String> cmd = new ArrayList<>(Arrays.asList(Arrays.copyOfRange(args, i, args.length)));
        if (cmd.isEmpty()) {
            usage();
            return 2;
        }
        String root = new File(".").getCanonicalPath();
        if (out == null) out = root + "/.fenvix";
        File outDir = new File(out).getCanonicalFile();
        out = outDir.getPath();
        // fresh parts for this run
        File parts = new File(outDir, "parts");
        File[] old = parts.listFiles();
        if (old != null) for (File f : old) f.delete();
        File depsDir = new File(outDir, "deps");
        File[] oldDeps = depsDir.listFiles();
        if (oldDeps != null) for (File f : oldDeps) f.delete();
        Path assets = assets();
        String tool = new File(cmd.get(0)).getName();
        List<String> props = new ArrayList<>();
        props.add("-Dfenvix.agent=" + self());
        if (det) props.add("-Dfenvix.det=1");
        if (deps) props.add("-Dfenvix.deps=1");
        props.add("-Dfenvix.seed=" + seed);
        props.add("-Dfenvix.root=" + root);
        props.add("-Dfenvix.out=" + out);
        if (!disable.isEmpty()) props.add("-Dfenvix.disable=" + disable);
        if (!allow.isEmpty()) props.add("-Dfenvix.allow.hosts=" + allow);
        List<String> full = new ArrayList<>();
        full.add(cmd.get(0));
        if (tool.startsWith("gradle")) {
            full.add("--init-script");
            full.add(assets.resolve("fenvix.init.gradle").toString());
            full.addAll(props);
        } else if (tool.startsWith("mvn")) {
            full.add("-Dmaven.ext.class.path=" + assets.resolve("fenvix-maven-ext.jar"));
            full.addAll(props);
        } else {
            System.err.println("fenvix-jvm: unknown build tool " + tool + " (gradle, gradlew, mvn, mvnw)");
            return 2;
        }
        full.addAll(cmd.subList(1, cmd.size()));
        Process p = new ProcessBuilder(full).inheritIO().start();
        int rc = p.waitFor();
        if (det) {
            String summary = merge(out);
            System.err.println("fenvix-jvm: trace " + new File(outDir, "trace.jsonl") + " " + summary);
        }
        return rc;
    }

    static void copy(String res, Path to) throws Exception {
        try (java.io.InputStream in = Main.class.getResourceAsStream(res)) {
            Files.copy(in, to, StandardCopyOption.REPLACE_EXISTING);
        }
    }
}
