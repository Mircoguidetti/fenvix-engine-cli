/* JNI: reads the first line of a file with fopen (native I/O, invisible to the JDK hooks). */
#include <jni.h>
#include <stdio.h>
#include <string.h>

JNIEXPORT jstring JNICALL Java_rv_NativeReader_firstLine(JNIEnv *env, jclass cls, jstring path) {
    const char *p = (*env)->GetStringUTFChars(env, path, NULL);
    char buf[256] = {0};
    FILE *f = fopen(p, "r");
    (*env)->ReleaseStringUTFChars(env, path, p);
    if (f == NULL) return NULL;
    if (fgets(buf, sizeof buf, f) == NULL) buf[0] = 0;
    fclose(f);
    buf[strcspn(buf, "\n")] = 0;
    return (*env)->NewStringUTF(env, buf);
}
