package dev.fenvix.rt;

import java.io.File;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Call sites arrive as {@code pkg/path/File.java:line} (known when the class is
 * rewritten); they are mapped to the source file relative to the repository
 * root, POSIX separators (the shared event vocabulary), when the file is found
 * under the root; otherwise the package path is kept (machine independent).
 */
final class Sites {
    private Sites() {}

    private static volatile Map<String, String> index;
    private static final ConcurrentHashMap<String, String> CACHE = new ConcurrentHashMap<>();

    static String resolve(String site) {
        if (site == null) return "";
        String c = CACHE.get(site);
        if (c != null) return c;
        int colon = site.lastIndexOf(':');
        String file = colon > 0 ? site.substring(0, colon) : site;
        String line = colon > 0 ? site.substring(colon) : "";
        String rel = index().get(file);
        String r = rel != null ? rel + line : site;
        if (CACHE.size() < 100_000) CACHE.put(site, r);
        return r;
    }

    static Map<String, String> index() {
        Map<String, String> i = index;
        if (i == null) {
            synchronized (Sites.class) {
                if (index == null) index = build();
                i = index;
            }
        }
        return i;
    }

    /** Source files under the root: key = path after a source root, value = path from the root. */
    private static Map<String, String> build() {
        Map<String, String> m = new HashMap<>();
        File root = new File(Det.ROOT.isEmpty() ? "." : Det.ROOT);
        walk(root, "", m, 0);
        return m;
    }

    private static void walk(File dir, String rel, Map<String, String> m, int depth) {
        if (depth > 24 || m.size() > 400_000) return;
        String[] names = dir.list();
        if (names == null) return;
        java.util.Arrays.sort(names);
        for (String n : names) {
            if (n.startsWith(".") || n.equals("build") || n.equals("target") || n.equals("node_modules") || n.equals("out")) continue;
            File f = new File(dir, n);
            String r = rel.isEmpty() ? n : rel + "/" + n;
            if (n.endsWith(".java") || n.endsWith(".kt") || n.endsWith(".groovy") || n.endsWith(".scala")) {
                // key: the path after .../java/, .../kotlin/, .../groovy/, .../scala/ (the package path)
                String key = r;
                for (String sr : new String[] {"/java/", "/kotlin/", "/groovy/", "/scala/"}) {
                    int k = r.lastIndexOf(sr);
                    if (k >= 0) {
                        key = r.substring(k + sr.length());
                        break;
                    }
                }
                m.putIfAbsent(key, r);
            } else if (f.isDirectory()) {
                walk(f, r, m, depth + 1);
            }
        }
    }
}
