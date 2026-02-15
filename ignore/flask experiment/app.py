import os
import re
import subprocess
import threading
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import tempfile
import time
from pathlib import Path

app = Flask(__name__, template_folder='.', static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB max file size
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
print(tempfile.gettempdir())

# Windows-specific: suppress console windows
SUBPROCESS_FLAGS = 0
if os.name == 'nt':
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW

# Store active compression jobs
compression_jobs = {}


def check_ffmpeg_installed():
    """Check if FFmpeg and FFprobe are installed"""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, creationflags=SUBPROCESS_FLAGS)
        subprocess.run(["ffprobe", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, creationflags=SUBPROCESS_FLAGS)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def safe_eval_expression(expr_str):
    """Safely evaluate mathematical expressions like '720/2' or '1920-100'"""
    try:
        expr_str = str(expr_str).strip()
        if not expr_str:
            return None
        # Only allow digits, basic operators, and parentheses
        if not all(c in '0123456789+-*/.() ' for c in expr_str):
            return None
        result = eval(expr_str)
        return result
    except:
        return None


def ensure_even(value):
    """Round down to nearest even number (required by libx264)"""
    if value is None:
        return None
    try:
        val = int(value)
        return val if val % 2 == 0 else val - 1
    except:
        return None


def get_video_info(filepath):
    """Get video duration, resolution, fps, and audio bitrate"""
    try:
        # Get duration
        command = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", filepath
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, 
                              creationflags=SUBPROCESS_FLAGS, timeout=10)
        duration = float(result.stdout.strip())
        
        # Get video info
        command = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "default=noprint_wrappers=1", filepath
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, 
                              creationflags=SUBPROCESS_FLAGS, timeout=10)
        output = result.stdout
        
        width_match = re.search(r"width=(\d+)", output)
        height_match = re.search(r"height=(\d+)", output)
        fps_match = re.search(r"r_frame_rate=(\d+)/(\d+)", output)
        
        width = int(width_match.group(1)) if width_match else None
        height = int(height_match.group(1)) if height_match else None
        
        fps = None
        if fps_match:
            numerator = int(fps_match.group(1))
            denominator = int(fps_match.group(2))
            fps = round(numerator / denominator, 2)
        
        # Get audio bitrate
        command = [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1", filepath
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, 
                              creationflags=SUBPROCESS_FLAGS, timeout=10)
        audio_bitrate = None
        try:
            audio_bitrate = int(result.stdout.strip()) // 1000  # Convert to kbps
        except:
            audio_bitrate = 128
        
        # Get file size
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        
        return {
            'duration': duration,
            'width': width,
            'height': height,
            'fps': fps,
            'audio_bitrate': audio_bitrate,
            'file_size_mb': round(file_size_mb, 2)
        }
    except Exception as e:
        print(f"Error getting video info: {e}")
        return None


def time_to_seconds(time_str):
    """Convert FFmpeg time format to seconds"""
    h, m, s = time_str.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def compress_video(job_id, input_file, output_file, settings):
    """Compress video with FFmpeg"""
    try:
        compression_jobs[job_id]['status'] = 'processing'
        compression_jobs[job_id]['progress'] = 0
        
        vf_filters = []
        
        # Resolution
        if settings['width'] and settings['height']:
            width = ensure_even(settings['width'])
            height = ensure_even(settings['height'])
            vf_filters.append(f"scale={width}:{height}")
        
        # FPS
        if settings['fps']:
            vf_filters.append(f"fps={settings['fps']}")
        
        vf_string = ",".join(vf_filters) if vf_filters else None
        
        command = [
            "ffmpeg", "-y", "-i", input_file,
            "-c:v", "libx264",
            "-preset", settings.get('preset', 'medium'),
            "-b:v", str(settings['video_bitrate']),
        ]
        
        if settings.get('tune'):
            command.extend(["-tune", settings['tune']])
        
        if settings.get('mute_audio'):
            command.extend(["-an"])
        else:
            command.extend(["-c:a", "aac", "-b:a", str(settings.get('audio_bitrate', 128000))])
        
        if vf_string:
            command.extend(["-vf", vf_string])
        
        command.append(output_file)
        
        print("FFmpeg Command:", " ".join(command))
        
        # Run FFmpeg
        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            creationflags=SUBPROCESS_FLAGS
        )
        
        duration = settings.get('duration', 10.0)
        
        for line in process.stderr:
            if "time=" in line:
                time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if time_match:
                    seconds = time_to_seconds(time_match.group(1))
                    percent = int((seconds / duration) * 100)
                    compression_jobs[job_id]['progress'] = min(percent, 100)
        
        process.wait()
        
        if process.returncode == 0:
            compression_jobs[job_id]['status'] = 'completed'
            compression_jobs[job_id]['progress'] = 100
            compression_jobs[job_id]['output_file'] = output_file
            
            # Get output file size
            output_size_mb = os.path.getsize(output_file) / (1024 * 1024)
            compression_jobs[job_id]['output_size_mb'] = round(output_size_mb, 2)
        else:
            compression_jobs[job_id]['status'] = 'failed'
            compression_jobs[job_id]['error'] = 'FFmpeg process failed'
            
    except Exception as e:
        compression_jobs[job_id]['status'] = 'failed'
        compression_jobs[job_id]['error'] = str(e)
        print(f"Compression error: {e}")


@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')


@app.route('/check_ffmpeg')
def check_ffmpeg():
    """Check if FFmpeg is installed"""
    return jsonify({'installed': check_ffmpeg_installed()})


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and extract video info"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Save file
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    # Get video info
    info = get_video_info(filepath)
    if info is None:
        return jsonify({'error': 'Failed to read video file'}), 400
    
    return jsonify({
        'success': True,
        'filepath': filepath,
        'filename': filename,
        'info': info
    })


@app.route('/compress', methods=['POST'])
def start_compression():
    """Start video compression"""
    data = request.json
    
    input_file = data.get('input_file')
    if not input_file or not os.path.exists(input_file):
        return jsonify({'error': 'Invalid input file'}), 400
    
    # Generate job ID
    job_id = str(int(time.time() * 1000))
    
    # Prepare output file
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_name}_compressed_{job_id}.mp4")
    
    # Prepare settings
    settings = {
        'width': ensure_even(safe_eval_expression(data.get('width'))),
        'height': ensure_even(safe_eval_expression(data.get('height'))),
        'fps': safe_eval_expression(data.get('fps')),
        'preset': data.get('preset', 'medium'),
        'mute_audio': data.get('mute_audio', False),
        'duration': data.get('duration', 10.0)
    }
    
    # Tune (optional)
    tune = data.get('tune')
    if tune and tune != 'None':
        settings['tune'] = tune
    
    # Audio bitrate
    audio_bitrate = safe_eval_expression(data.get('audio_bitrate', 128))
    settings['audio_bitrate'] = int(audio_bitrate * 1000) if audio_bitrate else 128000
    
    # Calculate video bitrate
    target_mb = safe_eval_expression(data.get('target_size'))
    if target_mb is None or target_mb <= 0:
        return jsonify({'error': 'Invalid target size'}), 400
    
    duration = settings['duration']
    target_bits = target_mb * 1024 * 1024 * 8
    video_bitrate = (target_bits / duration) - settings['audio_bitrate']
    video_bitrate *= 0.97  # safety margin
    
    if video_bitrate < 100:
        return jsonify({'error': 'Target size too small'}), 400
    
    settings['video_bitrate'] = int(video_bitrate)
    
    # Initialize job
    compression_jobs[job_id] = {
        'status': 'pending',
        'progress': 0,
        'input_file': input_file,
        'output_file': None
    }
    
    # Start compression in background thread
    thread = threading.Thread(target=compress_video, args=(job_id, input_file, output_file, settings))
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'job_id': job_id})


@app.route('/status/<job_id>')
def get_status(job_id):
    """Get compression job status"""
    if job_id not in compression_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = compression_jobs[job_id]
    return jsonify({
        'status': job['status'],
        'progress': job['progress'],
        'output_size_mb': job.get('output_size_mb'),
        'error': job.get('error')
    })


@app.route('/download/<job_id>')
def download_file(job_id):
    """Download compressed video"""
    if job_id not in compression_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = compression_jobs[job_id]
    if job['status'] != 'completed' or not job.get('output_file'):
        return jsonify({'error': 'File not ready'}), 400
    
    output_file = job['output_file']
    if not os.path.exists(output_file):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(output_file, as_attachment=True, 
                    download_name=os.path.basename(output_file))


if __name__ == '__main__':
    # Check FFmpeg on startup
    if not check_ffmpeg_installed():
        print("\n" + "="*60)
        print("ERROR: FFmpeg is not installed or not in PATH")
        print("="*60)
        print("\nPlease install FFmpeg:")
        print("  Windows: winget install FFmpeg")
        print("  macOS:   brew install ffmpeg")
        print("  Linux:   sudo apt-get install ffmpeg")
        print("\n" + "="*60 + "\n")
        exit(1)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
