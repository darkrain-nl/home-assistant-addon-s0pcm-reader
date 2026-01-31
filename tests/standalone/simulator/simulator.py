import socket
import time

HOST = "0.0.0.0"
PORT = 2000


def run_server():
    print(f"Starting simulator on {HOST}:{PORT}...", flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        print("Listening...", flush=True)

        while True:
            try:
                conn, addr = s.accept()
                with conn:
                    print(f"Connected by {addr}", flush=True)
                    while True:
                        # Send Header
                        conn.sendall(b"/8237:S0 Pulse Counter V0.6 - 30/30/30/30/30ms\r\n")
                        time.sleep(0.1)
                        # Send Data
                        # ID:8237:I:10:M1:0:100:M2:0:50
                        # Increment pulses to show activity if verified? For now static is fine.
                        conn.sendall(b"ID:8237:I:10:M1:0:100:M2:0:50\r\n")
                        print("Sent packet", flush=True)
                        time.sleep(5)
            except Exception as e:
                print(f"Connection lost: {e}", flush=True)
                time.sleep(1)


if __name__ == "__main__":
    run_server()
