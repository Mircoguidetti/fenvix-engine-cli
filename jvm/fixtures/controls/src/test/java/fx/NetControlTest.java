package fx;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.net.ConnectException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.UnknownHostException;
import java.nio.channels.SocketChannel;
import org.junit.jupiter.api.Test;

/** Control "net": the network is closed (loopback allowed) under --det. */
class NetControlTest {
    @Test
    void externalConnectIsRefused() {
        ConnectException e = assertThrows(ConnectException.class, () -> {
            try (Socket s = new Socket()) {
                s.connect(new InetSocketAddress(InetAddress.getByAddress(new byte[] {93, (byte) 184, (byte) 215, 14}), 80), 3000);
            }
        });
        assertTrue(e.getMessage().contains("fenvix"), e.getMessage());
    }

    @Test
    void externalChannelConnectIsRefused() {
        IOException e = assertThrows(IOException.class, () -> {
            try (SocketChannel c = SocketChannel.open()) {
                c.connect(new InetSocketAddress(InetAddress.getByAddress(new byte[] {1, 1, 1, 1}), 443));
            }
        });
        assertTrue(String.valueOf(e.getMessage()).contains("fenvix"), String.valueOf(e.getMessage()));
    }

    @Test
    void externalDnsIsRefused() {
        UnknownHostException e = assertThrows(UnknownHostException.class, () -> InetAddress.getByName("example.com"));
        assertTrue(e.getMessage().contains("fenvix"), e.getMessage());
    }

    @Test
    void loopbackIsAllowed() throws Exception {
        try (ServerSocket ss = new ServerSocket(0, 1, InetAddress.getLoopbackAddress());
             Socket c = new Socket(InetAddress.getLoopbackAddress(), ss.getLocalPort());
             Socket a = ss.accept()) {
            c.getOutputStream().write(42);
            assertEquals(42, a.getInputStream().read());
        }
    }
}
