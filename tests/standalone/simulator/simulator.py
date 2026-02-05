import socket
import time

HOST = socket.gethostbyname(socket.gethostname())
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
                    counter_1 = 100
                    counter_2 = 50
                    while True:
                        # Send Header
                        conn.sendall(b"/8237:S0 Pulse Counter V0.6 - 30/30/30/30/30ms\r\n")
                        time.sleep(0.1)
                        # Send Data
                        # ID:8237:I:10:M1:0:100:M2:0:50
                        # Increment pulses to show activity
                        counter_1 += 1
                        counter_2 += 2
                        data = f"ID:8237:I:10:M1:0:{counter_1}:M2:0:{counter_2}\r\n"
                        conn.sendall(data.encode("ascii"))
                        print(f"Sent packet: {data.strip()}", flush=True)
                        time.sleep(1)
            except Exception as e:
                print(f"Connection lost: {e}", flush=True)
                time.sleep(1)


if __name__ == "__main__":
    run_server()
