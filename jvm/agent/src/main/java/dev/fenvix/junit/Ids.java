package dev.fenvix.junit;

import java.util.ArrayList;
import java.util.List;

/**
 * Test ids from JUnit Platform unique ids:
 * {@code [engine:junit-jupiter]/[class:a.B]/[method:t(int)]} becomes {@code a.B::t(int)},
 * template and dynamic invocations get {@code [n]}, nested classes are one more
 * level ({@code a.B::Inner::t()}), vintage ({@code [runner:a.B]/[test:t(a.B)]})
 * becomes {@code a.B::t}. A non-empty module (Gradle project path, Maven
 * artifactId) prefixes the id: {@code core::a.B::t()}.
 */
public final class Ids {
    private Ids() {}

    public static String fromUniqueId(String uid, String module) {
        List<String> parts = new ArrayList<>();
        String pendingTemplate = null;
        int i = 0;
        while (i < uid.length()) {
            int open = uid.indexOf('[', i);
            if (open < 0) break;
            int colon = uid.indexOf(':', open);
            int close = findClose(uid, colon);
            if (colon < 0 || close < 0) break;
            String type = uid.substring(open + 1, colon);
            String value = uid.substring(colon + 1, close);
            i = close + 1;
            switch (type) {
                case "engine":
                    break;
                case "test-template-invocation":
                case "dynamic-test":
                case "dynamic-container": {
                    String n = value.startsWith("#") ? value.substring(1) : value;
                    if (!parts.isEmpty()) parts.set(parts.size() - 1, parts.get(parts.size() - 1) + "[" + n + "]");
                    else parts.add("[" + n + "]");
                    break;
                }
                case "test": {
                    // vintage: name(class)
                    int p = value.lastIndexOf('(');
                    parts.add(p > 0 && value.endsWith(")") ? value.substring(0, p) : value);
                    break;
                }
                default:
                    parts.add(value);
            }
        }
        String id = String.join("::", parts);
        return module == null || module.isEmpty() ? id : module + "::" + id;
    }

    static int findClose(String s, int from) {
        if (from < 0) return -1;
        int depth = 0;
        for (int k = from; k < s.length(); k++) {
            char c = s.charAt(k);
            if (c == '[') depth++;
            else if (c == ']') {
                if (depth == 0) return k;
                depth--;
            }
        }
        return -1;
    }

    /** Module name normalised for ids (Gradle ':a:b' -> 'a/b'; root -> ''). */
    public static String module(String m) {
        if (m == null) return "";
        String s = m.startsWith(":") ? m.substring(1) : m;
        return s.replace(':', '/');
    }
}
