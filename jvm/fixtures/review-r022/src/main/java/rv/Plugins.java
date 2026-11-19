package rv;

/** Optional plug-in found by name at run time (Class.forName with a computed name). */
public final class Plugins {
    private Plugins() {}

    public static String active() {
        String name = Plugins.class.getPackage().getName() + ".ext." + "Plugin";
        try {
            Class.forName(name);
            return "plugin";
        } catch (ClassNotFoundException e) {
            return "default";
        }
    }
}
