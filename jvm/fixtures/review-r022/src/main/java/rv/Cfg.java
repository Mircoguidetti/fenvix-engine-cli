package rv;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;

/** An annotation whose default value is read reflectively. */
@Retention(RetentionPolicy.RUNTIME)
public @interface Cfg {
    int retries() default 3;
}
