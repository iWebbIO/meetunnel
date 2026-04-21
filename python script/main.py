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
        self.root.title("QR Network Tunnel v1.0")
        self.root.geometry("500x650")
        self.running = False
        
        # UI Setup
        self.tab_control = ttk.Notebook(root)
        self.send_tab = ttk.Frame(self.tab_control)
        self.recv_tab = ttk.Frame(self.tab_control)
        
        self.tab_control.add(self.send_tab, text='Sender (Data -> QR)')
        self.tab_control.add(self.recv_tab, text='Receiver (QR -> Data)')
        self.tab_control.pack(expand=1, fill="both")
        
        self.reassembly_buffer = {} # Stores fragments: {packet_id: [frag0, frag1, ...]}
        self.web_frame = None
        self.use_web_capture = tk.BooleanVar(value=False)
        self.setup_send_tab()
        self.setup_recv_tab()
        
        # Log Window
        self.log_area = scrolledtext.ScrolledText(root, height=12)
        self.log_area.pack(fill="both", padx=10, pady=10)
        self.log("System Ready. Please install UnityCapture before starting.")

    def log(self, message):
        self.log_area.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_area.see(tk.END)

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
            threading.Thread(target=self.run_sender_logic, daemon=True).start()
        else:
            self.running = False
            self.btn_send.config(text="Start Sender")

    def toggle_receiver(self):
        if not self.running:
            self.running = True
            self.btn_recv.config(text="Stop Receiver")
            if self.use_web_capture.get():
                threading.Thread(target=self.run_web_server, daemon=True).start()
            threading.Thread(target=self.run_receiver_logic, daemon=True).start()
        else:
            self.running = False
            self.btn_recv.config(text="Start Receiver")

    def run_web_server(self):
        outer_self = self
        class FrameHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                try:
                    # Data comes in as 'data:image/jpeg;base64,...'
                    header, encoded = post_data.decode().split(",", 1)
                    nparr = np.frombuffer(base64.b64decode(encoded), np.uint8)
                    outer_self.web_frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    self.send_response(200)
                    self.end_headers()
                except: self.send_response(400); self.end_headers()
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
                while self.running:
                    packet_datas = []
                    try:
                        # Increase buffer to handle standard MTU sizes
                        full_data, addr = sock.recvfrom(2048) 
                        chunk_size = 350
                        total_frags = math.ceil(len(full_data) / chunk_size)
                        
                        for i in range(total_frags):
                            chunk = full_data[i*chunk_size : (i+1)*chunk_size]
                            # Header v1.1: Magic(2), Ver(1), Type(1), PktID(4), FragIdx(1), FragTotal(1), Len(2)
                            header = struct.pack("!2s B B I B B H", PROTOCOL_MAGIC, PROTOCOL_VERSION, TYPE_DATA, seq, i, total_frags, len(chunk))
                            packet_datas.append(header + chunk)
                        
                        self.log(f"Sending Pkt {seq} ({total_frags} frags)")
                        seq += 1 
                    except socket.timeout:
                        header = struct.pack("!2s B B I B B H", PROTOCOL_MAGIC, PROTOCOL_VERSION, TYPE_HANDSHAKE, 0, 0, 1, 7)
                        packet_datas = [header + b"SYNC_V1"]

                    for p_data in packet_datas:
                        qr = qrcode.QRCode(version=10, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=2)
                        qr.add_data(p_data.decode('latin-1'))
                        qr.make(fit=True)
                        img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
                        frame = np.array(img)
                        frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_NEAREST)
                        cam.send(frame)
                        cam.sleep_until_next_frame()

        except Exception as e:
            self.log(f"Sender Error: {e}")
            self.running = False

    def run_receiver_logic(self):
        port = int(self.recv_port.get())
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # OpenCV built-in detector (No libiconv.dll required)
        detector = cv2.QRCodeDetector()
        
        self.log("Receiver scanning screen...")
        last_seq = -1
        
        with mss.mss() as sct:
            while self.running:
                if self.use_web_capture.get() and self.web_frame is not None:
                    frame = self.web_frame
                else:
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
                        raw_payload = data.encode('latin-1')
                        if len(raw_payload) >= 12:
                            magic, ver, ptype, pkt_id, f_idx, f_total, plen = struct.unpack("!2s B B I B B H", raw_payload[:12])
                            
                            if magic == PROTOCOL_MAGIC and ver == PROTOCOL_VERSION:
                                chunk_data = raw_payload[12:12+plen]
                                
                                if ptype == TYPE_HANDSHAKE:
                                    if pkt_id < last_seq or last_seq == -1:
                                        self.log("Handshake - Session Synchronized")
                                        last_seq = pkt_id
                                
                                elif ptype == TYPE_DATA:
                                    if pkt_id <= last_seq: continue
                                    
                                    if pkt_id not in self.reassembly_buffer:
                                        self.reassembly_buffer[pkt_id] = [None] * f_total
                                    
                                    self.reassembly_buffer[pkt_id][f_idx] = chunk_data
                                    
                                    # Check if all fragments arrived
                                    if all(f is not None for f in self.reassembly_buffer[pkt_id]):
                                        full_packet = b''.join(self.reassembly_buffer[pkt_id])
                                        sock.sendto(full_packet, ("127.0.0.1", port))
                                        self.log(f"Reassembled Pkt {pkt_id} ({len(full_packet)} bytes)")
                                        last_seq = pkt_id
                                        del self.reassembly_buffer[pkt_id]
                                        # Clean up old buffers
                                        if len(self.reassembly_buffer) > 10: self.reassembly_buffer.clear()
                                    
                    except Exception as e:
                        self.log(f"Protocol Error: {e}")
                
                time.sleep(0.03) # ~30 FPS scan rate

if __name__ == "__main__":
    root = tk.Tk()
    app = QRTunnelGUI(root)
    root.mainloop()