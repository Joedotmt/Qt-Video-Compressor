import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sys
import os
import subprocess
import re
import threading
import queue
import time

# Constants
AUDIO_BITRATE_DEFAULT = 128_000  # 128 kbps

# Windows-specific: suppress console windows for subprocess
SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW

# -----------------------------
# Helpers
# -----------------------------
def check_ffmpeg_installed():
    """Check if FFmpeg and FFprobe are installed"""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, creationflags=SUBPROCESS_FLAGS)
        subprocess.run(["ffprobe", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, creationflags=SUBPROCESS_FLAGS)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def show_ffmpeg_error():
    message = (
        "FFmpeg is not installed or not in PATH.\n\n"
        "Windows: winget install FFmpeg\n"
        "macOS: brew install ffmpeg\n"
        "Linux: sudo apt-get install ffmpeg\n\n"
        "Please install and restart."
    )
    messagebox.showerror("FFmpeg Not Found", message)

def safe_eval_expression(expr_str):
    try:
        expr_str = str(expr_str).strip()
        if not expr_str: return None
        if not all(c in '0123456789+-*/.() ' for c in expr_str): return None
        return eval(expr_str)
    except:
        return None

def ensure_even(value):
    if value is None: return None
    try:
        val = int(value)
        return val if val % 2 == 0 else val - 1
    except:
        return None

def time_to_seconds(time_str):
    h, m, s = time_str.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

# -----------------------------
# FFmpeg Logic
# -----------------------------
def get_duration(input_file):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", input_file]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, creationflags=SUBPROCESS_FLAGS)
        return float(res.stdout)
    except:
        return 10.0

def get_source_audio_bitrate(input_file):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=bit_rate", "-of", "default=noprint_wrappers=1:nokey=1", input_file]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, creationflags=SUBPROCESS_FLAGS)
        return int(res.stdout.strip()) // 1000
    except:
        return 128

def get_source_video_info(input_file):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate", "-of", "default=noprint_wrappers=1", input_file]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, creationflags=SUBPROCESS_FLAGS)
        out = res.stdout
        w = re.search(r"width=(\d+)", out)
        h = re.search(r"height=(\d+)", out)
        fps = re.search(r"r_frame_rate=(\d+)/(\d+)", out)
        
        width = w.group(1) if w else ""
        height = h.group(1) if h else ""
        real_fps = ""
        if fps:
            real_fps = round(int(fps.group(1)) / int(fps.group(2)), 2)
        
        return width, height, str(real_fps)
    except:
        return "", "", ""

# -----------------------------
# Main Application
# -----------------------------
class VideoCompressorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        
        if not check_ffmpeg_installed():
            show_ffmpeg_error()
            self.destroy()
            sys.exit(1)

        self.title("Tkinter Video Compressor")
        self.geometry("600x650")
        self.resizable(False, False)

        # Apply a simple theme
        style = ttk.Style()
        style.theme_use('clam') 

        # State Variables
        self.input_file = None
        self.duration = 0
        self.source_audio_kbps = 128
        self.msg_queue = queue.Queue() # For thread communication

        # UI Variables
        self.var_target_mb = tk.StringVar()
        self.var_calc_bitrate = tk.StringVar(value="---")
        
        self.var_width = tk.StringVar()
        self.var_height = tk.StringVar()
        self.var_fps = tk.StringVar()
        self.var_vid_info = tk.StringVar(value="")

        self.var_audio_bitrate = tk.StringVar()
        self.var_mute = tk.BooleanVar(value=False)
        
        self.var_preset = tk.StringVar(value="medium")
        self.var_crf = tk.StringVar()
        self.var_tune = tk.StringVar(value="None")

        self.setup_ui()
        
        # Add traces for auto-calculation
        self.var_target_mb.trace_add("write", self.update_estimated_bitrate)
        self.var_audio_bitrate.trace_add("write", self.update_estimated_bitrate)
        self.var_mute.trace_add("write", self.update_estimated_bitrate)
        
        # Add traces for tiny video info preview
        self.var_width.trace_add("write", self.update_vid_info_label)
        self.var_height.trace_add("write", self.update_vid_info_label)
        self.var_fps.trace_add("write", self.update_vid_info_label)

        self.disable_controls()

    def setup_ui(self):
        main_pad = 20
        
        # 1. File Selection Area
        self.file_frame = tk.Frame(self, bd=2, relief="groove", bg="#f0f0f0", cursor="hand2")
        self.file_frame.pack(fill="x", padx=main_pad, pady=main_pad)
        self.file_frame.bind("<Button-1>", lambda e: self.browse_file())
        
        self.lbl_file = tk.Label(self.file_frame, text="Click to Select Video File", bg="#f0f0f0", fg="#555", font=("Arial", 12, "bold"), pady=30)
        self.lbl_file.pack()
        self.lbl_file.bind("<Button-1>", lambda e: self.browse_file())

        # 2. Notebook (Tabs)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=main_pad)

        # --- Tab 1: File Size ---
        tab1 = ttk.Frame(self.notebook)
        self.notebook.add(tab1, text="File Size")
        
        f1 = ttk.Frame(tab1, padding=20)
        f1.pack(fill="both", expand=True)
        
        # Row 1: Target Size
        ttk.Label(f1, text="Target Size (MB):").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(f1, textvariable=self.var_target_mb).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(f1, text="Match Source", command=self.load_source_size).grid(row=0, column=2)

        # Row 2: Calculated Bitrate
        ttk.Label(f1, text="Video Bitrate (kbps):").grid(row=1, column=0, sticky="w", pady=5)
        e_bit = ttk.Entry(f1, textvariable=self.var_calc_bitrate, state="readonly")
        e_bit.grid(row=1, column=1, sticky="ew", padx=5)
        
        f1.columnconfigure(1, weight=1)

        # --- Tab 2: Video ---
        tab2 = ttk.Frame(self.notebook)
        self.notebook.add(tab2, text="Video")
        f2 = ttk.Frame(tab2, padding=20)
        f2.pack(fill="both", expand=True)

        ttk.Label(f2, text="Width:").grid(row=0, column=0, sticky="e")
        ttk.Entry(f2, textvariable=self.var_width).grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        
        ttk.Label(f2, text="Height:").grid(row=1, column=0, sticky="e")
        ttk.Entry(f2, textvariable=self.var_height).grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        
        ttk.Label(f2, text="FPS:").grid(row=2, column=0, sticky="e")
        ttk.Entry(f2, textvariable=self.var_fps).grid(row=2, column=1, sticky="ew", padx=5, pady=5)

        ttk.Button(f2, text="Use Source Settings", command=self.load_source_video_settings).grid(row=3, column=1, pady=10, sticky="ew")
        
        # Tiny preview label
        ttk.Label(f2, textvariable=self.var_vid_info, foreground="gray", font=("Arial", 8)).grid(row=4, column=1)

        f2.columnconfigure(1, weight=1)

        # --- Tab 3: Audio ---
        tab3 = ttk.Frame(self.notebook)
        self.notebook.add(tab3, text="Audio")
        f3 = ttk.Frame(tab3, padding=20)
        f3.pack(fill="both", expand=True)

        ttk.Checkbutton(f3, text="Mute Audio", variable=self.var_mute).pack(anchor="w", pady=5)
        
        frame_aud = ttk.Frame(f3)
        frame_aud.pack(fill="x", pady=5)
        ttk.Label(frame_aud, text="Bitrate (kbps):").pack(side="left")
        ttk.Entry(frame_aud, textvariable=self.var_audio_bitrate).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(frame_aud, text="Match Source", command=self.load_source_audio).pack(side="left")

        # --- Tab 4: Encoder ---
        tab4 = ttk.Frame(self.notebook)
        self.notebook.add(tab4, text="Encoder")
        f4 = ttk.Frame(tab4, padding=20)
        f4.pack(fill="both", expand=True)

        ttk.Label(f4, text="Preset:").grid(row=0, column=0, sticky="w", pady=5)
        preset_cb = ttk.Combobox(f4, textvariable=self.var_preset, state="readonly")
        preset_cb['values'] = ('ultrafast', 'fast', 'medium', 'slow', 'veryslow')
        preset_cb.grid(row=0, column=1, sticky="ew", padx=5)

        ttk.Label(f4, text="CRF (0-51):").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(f4, textvariable=self.var_crf).grid(row=1, column=1, sticky="ew", padx=5)
        ttk.Label(f4, text="(Overrides target size)").grid(row=1, column=2, padx=5)

        ttk.Label(f4, text="Tune:").grid(row=2, column=0, sticky="w", pady=5)
        tune_cb = ttk.Combobox(f4, textvariable=self.var_tune, state="readonly")
        tune_cb['values'] = ('None', 'film', 'animation', 'grain', 'stillimage')
        tune_cb.grid(row=2, column=1, sticky="ew", padx=5)
        
        f4.columnconfigure(1, weight=1)

        # 3. Footer
        self.progress = ttk.Progressbar(self, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", padx=main_pad, pady=(0, 10))

        self.btn_compress = ttk.Button(self, text="Compress Video", command=self.start_compression)
        self.btn_compress.pack(fill="x", padx=main_pad, pady=(0, main_pad))

    # -----------------------------
    # Logic
    # -----------------------------
    def browse_file(self):
        path = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.avi *.mkv *.mov *.flv *.wmv")])
        if path:
            self.input_file = path
            self.lbl_file.config(text=os.path.basename(path), fg="black", bg="#d9d9d9")
            self.enable_controls()
            
            # Load Data
            self.duration = get_duration(path)
            self.source_audio_kbps = get_source_audio_bitrate(path)
            
            # Defaults
            self.load_source_size()
            self.load_source_video_settings()
            self.load_source_audio()
            self.update_estimated_bitrate()

    def enable_controls(self):
        for child in self.winfo_children():
            try: child.state(["!disabled"]) 
            except: pass
        self.btn_compress.state(["!disabled"])

    def disable_controls(self):
        # We don't disable the entire window, just inputs
        # But for simplicity in Tkinter, checking self.input_file in start_compression is usually enough
        # Visually disabling everything is tedious in Tkinter without a loop
        if not self.input_file:
            self.btn_compress.state(["disabled"])

    def load_source_size(self):
        if not self.input_file: return
        try:
            size_mb = os.path.getsize(self.input_file) / (1024 * 1024)
            self.var_target_mb.set(f"{size_mb:.2f}")
        except: pass

    def load_source_video_settings(self):
        if not self.input_file: return
        w, h, f = get_source_video_info(self.input_file)
        self.var_width.set(w)
        self.var_height.set(h)
        self.var_fps.set(f)

    def load_source_audio(self):
        if not self.input_file: return
        self.var_audio_bitrate.set(str(self.source_audio_kbps))

    def update_estimated_bitrate(self, *args):
        if not self.duration: return
        
        target_mb = safe_eval_expression(self.var_target_mb.get())
        if target_mb is None:
            self.var_calc_bitrate.set("---")
            return

        is_muted = self.var_mute.get()
        audio_kbps = 0
        if not is_muted:
            val = safe_eval_expression(self.var_audio_bitrate.get())
            audio_kbps = val if val is not None else 128
        
        # Calculation: (TargetMB * 8192 / duration) - audio_kbps
        # 8192 = 1024*1024*8 / 1000 (to get kbps directly)
        
        total_kbps = (target_mb * 8192) / self.duration
        video_kbps = total_kbps - audio_kbps
        video_kbps *= 0.97 # Safety margin
        
        if video_kbps < 0: video_kbps = 0
        self.var_calc_bitrate.set(str(int(video_kbps)))

    def update_vid_info_label(self, *args):
        w = self.var_width.get()
        h = self.var_height.get()
        f = self.var_fps.get()
        self.var_vid_info.set(f"{w}x{h} @ {f}fps")

    # -----------------------------
    # Compression Execution
    # -----------------------------
    def start_compression(self):
        if not self.input_file: return

        # Validation
        crf = safe_eval_expression(self.var_crf.get())
        vid_bitrate = 0
        
        width = ensure_even(safe_eval_expression(self.var_width.get()))
        height = ensure_even(safe_eval_expression(self.var_height.get()))
        fps = safe_eval_expression(self.var_fps.get())
        
        if not width or not height or not fps:
            messagebox.showerror("Error", "Invalid Video Dimensions or FPS")
            return

        if crf is None:
            # Bitrate mode
            vid_bitrate_str = self.var_calc_bitrate.get()
            if vid_bitrate_str == "---" or int(vid_bitrate_str) < 100:
                messagebox.showerror("Error", "Target size too small or invalid.")
                return
            vid_bitrate = int(vid_bitrate_str) * 1000 # to bps
        
        audio_bitrate_val = safe_eval_expression(self.var_audio_bitrate.get())
        audio_bitrate = int(audio_bitrate_val * 1000) if audio_bitrate_val else 128000

        # Ask for save file
        base = os.path.splitext(os.path.basename(self.input_file))[0]
        output_path = filedialog.asksaveasfilename(initialfile=f"{base}_c.mp4", defaultextension=".mp4", filetypes=[("MP4", "*.mp4")])
        if not output_path: return

        # UI Lock
        self.btn_compress.config(state="disabled")
        self.progress['value'] = 0

        # Start Thread
        params = {
            'input': self.input_file,
            'output': output_path,
            'v_bitrate': vid_bitrate,
            'vf': f"scale={width}:{height},fps={fps}",
            'preset': self.var_preset.get(),
            'crf': crf,
            'tune': self.var_tune.get(),
            'mute': self.var_mute.get(),
            'a_bitrate': audio_bitrate,
            'duration': self.duration
        }

        t = threading.Thread(target=self.run_ffmpeg, args=(params,))
        t.start()
        
        # Start monitoring loop
        self.monitor_queue()

    def run_ffmpeg(self, p):
        cmd = ["ffmpeg", "-y", "-i", p['input'], "-c:v", "libx264", "-preset", p['preset']]
        
        if p['crf'] is not None:
            cmd.extend(["-crf", str(p['crf'])])
        else:
            cmd.extend(["-b:v", str(p['v_bitrate'])])
            
        if p['tune'] != "None":
            cmd.extend(["-tune", p['tune']])
            
        cmd.extend(["-vf", p['vf']])
        
        if p['mute']:
            cmd.append("-an")
        else:
            cmd.extend(["-c:a", "aac", "-b:a", str(p['a_bitrate'])])
            
        cmd.append(p['output'])
        
        print("Running:", " ".join(cmd))

        process = subprocess.Popen(
            cmd, 
            stderr=subprocess.PIPE, 
            universal_newlines=True, 
            creationflags=SUBPROCESS_FLAGS
        )

        for line in process.stderr:
            if "time=" in line:
                time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if time_match:
                    secs = time_to_seconds(time_match.group(1))
                    pct = int((secs / p['duration']) * 100)
                    self.msg_queue.put(("PROGRESS", min(pct, 100)))

        process.wait()
        self.msg_queue.put(("DONE", None))

    def monitor_queue(self):
        try:
            while True:
                msg, data = self.msg_queue.get_nowait()
                if msg == "PROGRESS":
                    self.progress['value'] = data
                elif msg == "DONE":
                    self.btn_compress.config(state="normal")
                    self.progress['value'] = 100
                    messagebox.showinfo("Success", "Compression Complete!")
                    return # Stop monitoring
        except queue.Empty:
            pass
        
        # Check again in 100ms
        self.after(100, self.monitor_queue)

if __name__ == "__main__":
    app = VideoCompressorApp()
    app.mainloop()