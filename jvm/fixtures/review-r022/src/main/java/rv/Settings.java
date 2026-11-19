package rv;

import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;

/** Optional classpath resource with a built-in default. */
public final class Settings {
    private Settings() {}

    public static String mode() throws IOException {
        Properties p = new Properties();
        try (InputStream in = Settings.class.getResourceAsStream("/rv-optional.properties")) {
            if (in == null) return "default";
            p.load(in);
        }
        return p.getProperty("mode", "default");
    }
}
