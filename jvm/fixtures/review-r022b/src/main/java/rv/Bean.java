package rv;

/** A JavaBean read through java.beans.Introspector (a reflection-driven, JDK-cached view). */
public class Bean {
    private int a;
    private int b;

    public int getA() { return a; }
    public void setA(int a) { this.a = a; }
    public int getB() { return b; }
    public void setB(int b) { this.b = b; }
}
