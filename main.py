import sys
import time
import socket
import cv2
import numpy as np
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from http.server import BaseHTTPRequestHandler, HTTPServer
import base64
import math
import struct
import select

# Requirements: pip install qrcode pyvirtualcam opencv-python mss numpy
import qrcode
import pyvirtualcam
import mss

# Protocol Constants
PROTOCOL_MAGIC = b'QN'
PROTOCOL_VERSION = 1
TYPE_HANDSHAKE = 1
TYPE_DATA = 2

class QRTunnelGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MeeTunnel v1.0")
        self.root.geometry("500x650")
        self.running = False
        self.socks5_active = False
        self.role = tk.StringVar(value="host")
        
        # UI Setup
        self.tab_control = ttk.Notebook(root)
        self.send_tab = ttk.Frame(self.tab_control)
        self.recv_tab = ttk.Frame(self.tab_control)
        
        self.tab_control.add(self.send_tab, text='Sender (Data -> QR)')
        self.tab_control.add(self.recv_tab, text='Receiver (QR -> Data)')
        self.config_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.config_tab, text='Config & Guide')
        self.tab_control.pack(expand=1, fill="both")
        
        self.stats = {"sent": 0, "recv": 0, "errors": 0}
        self.reassembly_buffer = {} # {pkt_id: {"data": [frags], "timestamp": time.time()}}
        self.frame_lock = threading.Lock()
        self.web_frame = None
        self.use_web_capture = tk.BooleanVar(value=False)
        
        self.setup_send_tab()
        self.setup_recv_tab()
        self.setup_config_tab()
        
        # Status Bar
        self.status_frame = ttk.Frame(root)
        self.status_frame.pack(fill="x", padx=10)
        self.lbl_status = ttk.Label(self.status_frame, text="STATUS: IDLE", foreground="blue", font=('Helvetica', 10, 'bold'))
        self.lbl_status.pack(side="left")
        self.lbl_stats = ttk.Label(self.status_frame, text="S: 0 | R: 0 | E: 0")
        self.lbl_stats.pack(side="right")

        self.log_area = scrolledtext.ScrolledText(root, height=12)
        self.log_area.pack(fill="both", padx=10, pady=10)
        self.log("System Ready. Please install UnityCapture before starting.")

    def log(self, message):
        self.log_area.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_area.see(tk.END)

    def update_stats_ui(self):
        self.lbl_stats.config(text=f"Sent: {self.stats['sent']} | Recv: {self.stats['recv']} | Err: {self.stats['errors']}")

    def setup_send_tab(self):
        ttk.Label(self.send_tab, text="UDP Listen IP:").grid(column=0, row=0, padx=10, pady=5)
        self.send_ip = ttk.Entry(self.send_tab)
        self.send_ip.insert(0, "127.0.0.1")
        self.send_ip.grid(column=1, row=0)

        ttk.Label(self.send_tab, text="UDP Listen Port:").grid(column=0, row=1, padx=10, pady=5)
        self.send_port = ttk.Entry(self.send_tab)
        self.send_port.insert(0, "9000")
        self.send_port.grid(column=1, row=1)

        self.btn_send = ttk.Button(self.send_tab, text="Start Sender", command=self.toggle_sender)
        self.btn_send.grid(column=0, row=2, columnspan=2, pady=20)
        
        ttk.Label(self.send_tab, text="Note: Select 'Unity Video Capture' in Meet.", foreground="gray").grid(column=0, row=3, columnspan=2)

    def setup_recv_tab(self):
        coords_frame = ttk.LabelFrame(self.recv_tab, text="Screen Capture Area")
        coords_frame.grid(column=0, row=0, columnspan=2, padx=10, pady=10, sticky="ew")

        fields = [("Top:", "200"), ("Left:", "200"), ("Width:", "600"), ("Height:", "600")]
        self.coords = {}
        for i, (label, default) in enumerate(fields):
            ttk.Label(coords_frame, text=label).grid(column=0, row=i, padx=5, pady=2)
            entry = ttk.Entry(coords_frame)
            entry.insert(0, default)
            entry.grid(column=1, row=i, padx=5, pady=2)
            self.coords[label] = entry

        self.btn_select = ttk.Button(coords_frame, text="Select Area with Mouse", command=self.start_area_selection)
        self.btn_select.grid(column=0, row=4, columnspan=2, pady=5)

        self.chk_web = ttk.Checkbutton(self.recv_tab, text="Enable Chrome Extension Capture (Port 5001)", variable=self.use_web_capture)
        self.chk_web.grid(column=0, row=1, columnspan=2, pady=5)

        ttk.Label(self.recv_tab, text="Forward to Port:").grid(column=0, row=1, padx=10, pady=5)
        self.recv_port = ttk.Entry(self.recv_tab)
        self.recv_port.insert(0, "9001")
        self.recv_port.grid(column=1, row=2)

        self.btn_recv = ttk.Button(self.recv_tab, text="Start Receiver", command=self.toggle_receiver)
        self.btn_recv.grid(column=0, row=3, columnspan=2, pady=20)

    def setup_config_tab(self):
        role_frame = ttk.LabelFrame(self.config_tab, text="Device Role Selection")
        role_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Radiobutton(role_frame, text="Host (Final Destination/Egress)", variable=self.role, value="host").pack(anchor="w", padx=10)
        ttk.Radiobutton(role_frame, text="Client (Origin/Proxy Source)", variable=self.role, value="client").pack(anchor="w", padx=10)
        
        self.btn_proxy = ttk.Button(self.config_tab, text="Start SOCKS5 Proxy (Client Only)", command=self.toggle_socks5)
        self.btn_proxy.pack(pady=10)

        guide_frame = ttk.LabelFrame(self.config_tab, text="Complete Guide")
        guide_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        guide_text = (
            "1. PREREQUISITES: Install UnityCapture driver to provide the virtual camera.\n\n"
            "2. HOST SETUP:\n"
            "   - Set Role to 'Host'.\n"
            "   - Start Receiver to scan the Client's QR code video feed.\n"
            "   - The Host will forward data to the local target port.\n\n"
            "3. CLIENT SETUP:\n"
            "   - Set Role to 'Client'.\n"
            "   - Click 'Start SOCKS5 Proxy' (Listens on 127.0.0.1:1080).\n"
            "   - Configure your browser/app to use SOCKS5 proxy at 127.0.0.1:1080.\n"
            "   - Start Sender to transmit data via QR codes to the Host.\n\n"
            "4. TUNNELING:\n"
            "   - When you click 'Start Sender', a Handshake (SYNC) is sent immediately.\n"
            "   - Ensure the Receiver is active before starting the Sender for best sync."
        )
        
        self.guide_display = tk.Text(guide_frame, wrap="word", font=("Helvetica", 9), bg="#f0f0f0")
        self.guide_display.insert("1.0", guide_text)
        self.guide_display.config(state="disabled")
        self.guide_display.pack(fill="both", expand=True, padx=5, pady=5)

    def toggle_socks5(self):
        if not self.socks5_active:
            if self.role.get() != "client":
                self.log("Error: SOCKS5 Proxy is only intended for Client role.")
                return
            self.socks5_active = True
            self.btn_proxy.config(text="Stop SOCKS5 Proxy")
            threading.Thread(target=self.run_socks5_logic, daemon=True).start()
            self.log("SOCKS5 Proxy active on 127.0.0.1:1080")
        else:
            self.socks5_active = False
            self.btn_proxy.config(text="Start SOCKS5 Proxy (Client Only)")

    def start_area_selection(self):
        # Minimize main window to see the screen clearly
        self.root.withdraw()
        
        # Create a transparent overlay
        self.selector = tk.Toplevel(self.root)
        self.selector.attributes("-alpha", 0.3)
        self.selector.attributes("-fullscreen", True)
        self.selector.attributes("-topmost", True)
        self.selector.config(cursor="cross")

        self.canvas = tk.Canvas(self.selector, cursor="cross", bg="grey")
        self.canvas.pack(fill="both", expand=True)

        self.start_x = None
        self.start_y = None
        self.rect = None

        self.canvas.bind("<ButtonPress-1>", self.on_selection_start)
        self.canvas.bind("<B1-Motion>", self.on_selection_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_selection_end)

    def on_selection_start(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, 1, 1, outline='red', width=2)

    def on_selection_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_selection_end(self, event):
        left = min(self.start_x, event.x)
        top = min(self.start_y, event.y)
        width = abs(event.x - self.start_x)
        height = abs(event.y - self.start_y)

        for field, val in [("Left:", left), ("Top:", top), ("Width:", width), ("Height:", height)]:
            self.coords[field].delete(0, tk.END)
            self.coords[field].insert(0, str(val))

        self.selector.destroy()
        self.root.deiconify()
        self.log(f"Capture area updated: {width}x{height} at ({left}, {top})")

    def toggle_sender(self):
        if not self.running:
            self.running = True
            self.btn_send.config(text="Stop Sender")
            self.lbl_status.config(text="STATUS: SENDER ACTIVE", foreground="green")
            threading.Thread(target=self.run_sender_logic, daemon=True).start()
        else:
            self.running = False
            self.lbl_status.config(text="STATUS: IDLE", foreground="blue")
            self.btn_send.config(text="Start Sender")

    def toggle_receiver(self):
        if not self.running:
            self.running = True
            self.btn_recv.config(text="Stop Receiver")
            if self.use_web_capture.get():
                threading.Thread(target=self.run_web_server, daemon=True).start()
            self.lbl_status.config(text="STATUS: RECEIVER ACTIVE", foreground="green")
            threading.Thread(target=self.run_receiver_logic, daemon=True).start()
        else:
            self.running = False
            self.lbl_status.config(text="STATUS: IDLE", foreground="blue")
            self.btn_recv.config(text="Start Receiver")

    def run_web_server(self):
        outer_self = self
        class FrameHandler(BaseHTTPRequestHandler):
            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()

            def do_POST(self):
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                try:
                    header, encoded = post_data.decode().split(",", 1)
                    nparr = np.frombuffer(base64.b64decode(encoded), np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if img is not None:
                        with outer_self.frame_lock:
                            outer_self.web_frame = img
                        self.send_response(200)
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                    else:
                        raise ValueError("Failed to decode image")
                except Exception as e:
                    outer_self.log(f"Web Server Data Error: {e}")
                    self.send_response(400)
                    self.end_headers()
            def log_message(self, format, *args): return # Silent
        HTTPServer(('127.0.0.1', 5001), FrameHandler).serve_forever()

    def run_sender_logic(self):
        ip = self.send_ip.get()
        port = int(self.send_port.get())
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((ip, port))
        sock.settimeout(0.5)
        
        seq = 0
        self.log(f"Sender active on {ip}:{port}")
        
        try:
            # Connect to the virtual camera filter
            with pyvirtualcam.Camera(width=640, height=480, fps=15, device="Unity Video Capture") as cam:
                # Immediate Handshake on start
                self.log("Starting Tunnel: Sending Handshake...")
                hs_header = struct.pack("!2s B B I B B H", PROTOCOL_MAGIC, PROTOCOL_VERSION, TYPE_HANDSHAKE, 0, 0, 1, 7)
                self.send_qr_frame(cam, hs_header + b"SYNC_V1")
                
                while self.running:
                    packet_datas = []
                    try:
                        # Increase buffer to handle standard MTU sizes
                        full_data, addr = sock.recvfrom(2048) 
                        chunk_size = 300 # Slightly smaller for better reliability
                        total_frags = math.ceil(len(full_data) / chunk_size)
                        
                        for i in range(total_frags):
                            chunk = full_data[i*chunk_size : (i+1)*chunk_size]
                            # Header v1.1: Magic(2), Ver(1), Type(1), PktID(4), FragIdx(1), FragTotal(1), Len(2)
                            header = struct.pack("!2s B B I B B H", PROTOCOL_MAGIC, PROTOCOL_VERSION, TYPE_DATA, seq, i, total_frags, len(chunk))
                            packet_datas.append(header + chunk)
                        
                        self.log(f"Sending Pkt {seq} ({total_frags} frags)")
                        seq += 1 
                        self.stats["sent"] += 1
                    except socket.timeout:
                        header = struct.pack("!2s B B I B B H", PROTOCOL_MAGIC, PROTOCOL_VERSION, TYPE_HANDSHAKE, 0, 0, 1, 7)
                        packet_datas = [header + b"SYNC_V1"]
                        # Handshakes aren't counted in 'sent' stats to keep them meaningful

                    for p_data in packet_datas:
                        self.send_qr_frame(cam, p_data)
                        
                    self.root.after(0, self.update_stats_ui)

        except Exception as e:
            self.log(f"Sender Error: {e}")
            self.running = False

    def send_qr_frame(self, cam, p_data):
        qr = qrcode.QRCode(version=10, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=2)
        qr.add_data(p_data.decode('latin-1'))
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
        frame = np.array(img)
        frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_NEAREST)
        cam.send(frame)
        cam.sleep_until_next_frame()

    def run_socks5_logic(self):
        """Extremely minimal SOCKS5 to UDP forwarder for demonstration."""
        proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxy_sock.bind(('127.0.0.1', 1080))
        proxy_sock.listen(5)
        proxy_sock.settimeout(1.0)
        
        target_udp = ('127.0.0.1', int(self.send_port.get()))
        udp_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        while self.socks5_active:
            try:
                conn, addr = proxy_sock.accept()
                # Handshake: [Ver, NMethods, Methods] -> [Ver, Method]
                data = conn.recv(262)
                if not data or data[0] != 0x05: 
                    conn.close()
                    continue
                conn.sendall(b"\x05\x00") # No authentication
                
                # Note: Real SOCKS5 requires handling the CONNECT request here.
                payload = conn.recv(4096)
                udp_out.sendto(payload, target_udp)
                conn.close()
            except socket.timeout: continue
            except Exception as e: self.log(f"Proxy Error: {e}")

    def run_receiver_logic(self):
        port = int(self.recv_port.get())
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # OpenCV built-in detector (No libiconv.dll required)
        detector = cv2.QRCodeDetector()
        
        self.log("Receiver scanning screen...")
        last_seq = -1
        
        with mss.mss() as sct:
            while self.running:
                frame = None
                if self.use_web_capture.get():
                    with self.frame_lock:
                        if self.web_frame is not None:
                            frame = self.web_frame.copy()
                
                if frame is None:
                    monitor = {
                        "top": int(self.coords["Top:"].get()),
                        "left": int(self.coords["Left:"].get()),
                        "width": int(self.coords["Width:"].get()),
                        "height": int(self.coords["Height:"].get())
                    }
                    sct_img = sct.grab(monitor)
                    frame = np.array(sct_img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                
                # Detect and decode
                data, bbox, _ = detector.detectAndDecode(frame)

                if data:
                    try:
                        # Use latin-1 to preserve raw bytes from the sender
                        try:
                            raw_payload = data.encode('latin-1')
                        except UnicodeEncodeError:
                            continue # Skip malformed decodes

                        if len(raw_payload) >= 12:
                            magic, ver, ptype, pkt_id, f_idx, f_total, plen = struct.unpack("!2s B B I B B H", raw_payload[:12])
                            
                            if magic != PROTOCOL_MAGIC:
                                self.log(f"Invalid Magic: {magic}")
                                continue

                            chunk_data = raw_payload[12:12+plen]
                            if ptype == TYPE_HANDSHAKE:
                                self.log(f"Handshake rx (Ver: {ver}) - Resyncing...")
                                last_seq = -1 # Reset sequence to allow new stream
                            
                            elif ptype == TYPE_DATA:
                                if pkt_id > last_seq:
                                    
                                    if pkt_id not in self.reassembly_buffer:
                                        self.reassembly_buffer[pkt_id] = {
                                            "frags": [None] * f_total,
                                            "timestamp": time.time()
                                        }
                                    
                                    self.reassembly_buffer[pkt_id]["frags"][f_idx] = chunk_data
                                    
                                    if all(f is not None for f in self.reassembly_buffer[pkt_id]["frags"]):
                                        full_packet = b''.join(self.reassembly_buffer[pkt_id]["frags"])
                                        sock.sendto(full_packet, ("127.0.0.1", port))
                                        self.log(f"Reassembled Pkt {pkt_id} ({len(full_packet)} bytes)")
                                        last_seq = pkt_id
                                        del self.reassembly_buffer[pkt_id]
                                        self.stats["recv"] += 1

                        # Periodically clean up stale fragments (older than 5s)
                        now = time.time()
                        stale_ids = [k for k, v in self.reassembly_buffer.items() if now - v["timestamp"] > 5.0]
                        for k in stale_ids: del self.reassembly_buffer[k]
                                    
                    except Exception as e:
                        self.log(f"Protocol Error: {e}")
                        self.stats["errors"] += 1
                
                self.root.after(0, self.update_stats_ui)
                time.sleep(0.03) # ~30 FPS scan rate

if __name__ == "__main__":
    root = tk.Tk()
    app = QRTunnelGUI(root)
    root.mainloop()