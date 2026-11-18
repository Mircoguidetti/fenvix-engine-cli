package dev.fenvix.maven;

import java.util.ArrayList;
import java.util.List;
import java.util.Properties;
import javax.inject.Named;
import javax.inject.Singleton;
import org.apache.maven.AbstractMavenLifecycleParticipant;
import org.apache.maven.execution.MavenSession;
import org.apache.maven.model.Plugin;
import org.apache.maven.model.PluginExecution;
import org.apache.maven.project.MavenProject;
import org.codehaus.plexus.util.xml.Xpp3Dom;

/**
 * Maven core extension ({@code -Dmaven.ext.class.path=fenvix-maven-ext.jar}): the
 * Surefire configuration of the JVM shell. With {@code -Dfenvix.agent=<jar>} and
 * {@code -Dfenvix.det=1} (or {@code -Dfenvix.deps=1}) it rewrites, in every
 * project, the configuration of maven-surefire-plugin:
 * <ul>
 *   <li>argLine: {@code -javaagent:<jar>=<options>} first, the project's own argLine kept
 *       (and {@code @{argLine}} when JaCoCo prepares one);
 *   <li>under --det: forkCount=1, reuseForks=true, no parallel execution, runOrder
 *       alphabetical (seed 0) or random with the seed (Surefire >= 3.0.0-M6);
 *   <li>the JUnit 4 provider's run listener is attached by the agent itself (RunNotifier hook);
 *   <li>system properties fenvix.module, fenvix.tool, fenvix.plugins, fenvix.config.
 * </ul>
 */
@Named("fenvix")
@Singleton
public class FenvixMavenExtension extends AbstractMavenLifecycleParticipant {
    static boolean on(String v) {
        return v != null && (v.equals("1") || v.equalsIgnoreCase("true") || v.equalsIgnoreCase("yes"));
    }

    static String prop(MavenSession s, String k, String d) {
        Properties u = s.getUserProperties();
        String v = u.getProperty(k);
        if (v == null) v = s.getSystemProperties().getProperty(k);
        if (v == null) v = System.getenv(k.toUpperCase().replace('.', '_'));
        return v == null ? d : v;
    }

    @Override
    public void afterProjectsRead(MavenSession session) {
        String agent = prop(session, "fenvix.agent", null);
        if (agent == null) return;
        boolean det = on(prop(session, "fenvix.det", "0"));
        boolean deps = on(prop(session, "fenvix.deps", "0"));
        if (!det && !deps) return;
        String root = prop(session, "fenvix.root", session.getExecutionRootDirectory());
        String out = prop(session, "fenvix.out", root + "/.fenvix");
        String seed = prop(session, "fenvix.seed", "0");
        String disable = prop(session, "fenvix.disable", "");
        String allow = prop(session, "fenvix.allow.hosts", "");
        String extra = prop(session, "fenvix.jvmargs", "");
        String mvnVersion = System.getProperty("maven.version", session.getSystemProperties().getProperty("maven.version", "?"));
        List<String> o = new ArrayList<>();
        if (det) o.add("det=1");
        if (deps) o.add("deps=1");
        o.add("seed=" + seed);
        o.add("root=" + root);
        o.add("out=" + out);
        if (!disable.isEmpty()) o.add("disable=" + disable.replace(',', ';'));
        if (!allow.isEmpty()) o.add("allow.hosts=" + allow.replace(',', ';'));
        String javaagent = "-javaagent:" + agent + "=" + String.join(",", o) + (extra.isEmpty() ? "" : " " + extra);
        for (MavenProject p : session.getProjects()) {
            boolean jacoco = false;
            StringBuilder plugins = new StringBuilder();
            for (Plugin pl : p.getBuildPlugins()) {
                if (pl.getArtifactId().equals("jacoco-maven-plugin")) jacoco = true;
                plugins.append(pl.getGroupId()).append(':').append(pl.getArtifactId()).append(':').append(pl.getVersion()).append(';');
            }
            // "@{argLine}" (kept for JaCoCo) must resolve even when JaCoCo is skipped or sets nothing
            if (jacoco && p.getProperties().getProperty("argLine") == null) p.getProperties().setProperty("argLine", "");
            String module = p.getArtifactId();
            if (p.getBasedir() != null && p.getBasedir().getAbsolutePath().equals(root)) module = "";
            for (Plugin pl : p.getBuildPlugins()) {
                if (!pl.getArtifactId().equals("maven-surefire-plugin")) continue;
                Xpp3Dom c = (Xpp3Dom) pl.getConfiguration();
                if (c == null) {
                    c = new Xpp3Dom("configuration");
                    pl.setConfiguration(c);
                }
                configure(c, javaagent, jacoco, det, seed, module, mvnVersion, plugins.toString());
                for (PluginExecution e : pl.getExecutions()) {
                    Xpp3Dom ec = (Xpp3Dom) e.getConfiguration();
                    if (ec == null) {
                        ec = new Xpp3Dom("configuration");
                        e.setConfiguration(ec);
                    }
                    configure(ec, javaagent, jacoco, det, seed, module, mvnVersion, plugins.toString());
                }
            }
        }
    }

    static void set(Xpp3Dom c, String name, String value) {
        Xpp3Dom d = c.getChild(name);
        if (d == null) {
            d = new Xpp3Dom(name);
            c.addChild(d);
        }
        d.setValue(value);
    }

    static void remove(Xpp3Dom c, String name) {
        for (int i = c.getChildCount() - 1; i >= 0; i--) {
            if (c.getChild(i).getName().equals(name)) c.removeChild(i);
        }
    }

    static void configure(Xpp3Dom c, String javaagent, boolean jacoco, boolean det, String seed, String module, String mvn, String plugins) {
        Xpp3Dom arg = c.getChild("argLine");
        String existing = arg != null && arg.getValue() != null ? arg.getValue().trim() : (jacoco ? "@{argLine}" : "");
        if (!existing.contains("fenvix-agent")) set(c, "argLine", (javaagent + " " + existing).trim());
        if (det) {
            set(c, "forkCount", "1");
            set(c, "reuseForks", "true");
            remove(c, "parallel");
            remove(c, "threadCount");
            remove(c, "perCoreThreadCount");
            remove(c, "useUnlimitedThreads");
            remove(c, "forkMode");
            if ("0".equals(seed)) {
                set(c, "runOrder", "alphabetical");
            } else {
                set(c, "runOrder", "random");
                set(c, "runOrderRandomSeed", seed);
            }
            Xpp3Dom cp = c.getChild("configurationParameters");
            if (cp != null && cp.getValue() != null) {
                cp.setValue(cp.getValue().replaceAll("junit\\.jupiter\\.execution\\.parallel\\.enabled\\s*=\\s*true",
                        "junit.jupiter.execution.parallel.enabled=false"));
            }
        }
        Xpp3Dom spv = c.getChild("systemPropertyVariables");
        if (spv == null) {
            spv = new Xpp3Dom("systemPropertyVariables");
            c.addChild(spv);
        }
        set(spv, "fenvix.module", module);
        set(spv, "fenvix.tool", "maven " + mvn);
        set(spv, "fenvix.plugins", plugins);
        StringBuilder cfg = new StringBuilder();
        for (String k : new String[] {"includes", "excludes", "groups", "excludedGroups", "environmentVariables", "systemPropertyVariables"}) {
            Xpp3Dom d = c.getChild(k);
            if (d != null && !k.equals("systemPropertyVariables")) cfg.append(k).append('=').append(d.toString().replaceAll("\\s+", " ")).append('|');
        }
        set(spv, "fenvix.config", cfg.toString());
    }
}
