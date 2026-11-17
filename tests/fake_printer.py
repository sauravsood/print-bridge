"""Pretend to be a TSC printer on a TCP port: answer status polls, save jobs."""
import socket, sys, threading, pathlib

def serve(port, outdir):
    out = pathlib.Path(outdir); out.mkdir(parents=True, exist_ok=True)
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port)); srv.listen()
    n = 0
    while True:
        c, _ = srv.accept(); data = b""
        c.settimeout(1.0)
        try:
            while True:
                chunk = c.recv(65536)
                if not chunk: break
                data += chunk
                if data == b"\x1b!?": c.sendall(b"\x00")
        except socket.timeout:
            pass
        c.close()
        if data and data != b"\x1b!?":
            n += 1; (out / f"job{n}.tspl").write_bytes(data)

if __name__ == "__main__":
    serve(int(sys.argv[1]), sys.argv[2])
