package dev.fenvix.rt;

import java.util.List;
import java.util.Map;

/** Minimal JSON writer (the runtime has no dependencies). */
public final class Json {
    private Json() {}

    public static void str(StringBuilder sb, String s) {
        if (s == null) {
            sb.append("null");
            return;
        }
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        sb.append('"');
    }

    public static void strs(StringBuilder sb, List<String> l) {
        sb.append('[');
        for (int i = 0; i < l.size(); i++) {
            if (i > 0) sb.append(',');
            str(sb, l.get(i));
        }
        sb.append(']');
    }

    public static void map(StringBuilder sb, Map<String, String> m) {
        sb.append('{');
        boolean first = true;
        for (Map.Entry<String, String> e : m.entrySet()) {
            if (!first) sb.append(',');
            first = false;
            str(sb, e.getKey());
            sb.append(':');
            str(sb, e.getValue());
        }
        sb.append('}');
    }

    public static String quote(String s) {
        StringBuilder sb = new StringBuilder();
        str(sb, s);
        return sb.toString();
    }
}
