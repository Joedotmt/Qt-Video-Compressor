# Video Compressor - Flask Web Application

A modern web-based video compression tool built with Flask and FFmpeg. Features a sleek, retro-futuristic interface for compressing video files with granular control over encoding parameters.

## Features

- **Drag & Drop Interface**: Easy file upload with drag-and-drop support
- **Real-time Progress Tracking**: Live compression progress with visual feedback
- **Multiple Compression Modes**:
  - File size targeting
  - CRF (Constant Rate Factor) quality-based compression
  - Custom resolution and frame rate
  - Audio bitrate control or muting
- **Advanced Encoder Settings**:
  - Preset selection (ultrafast to slow)
  - Tune options (film, animation, grain, stillimage)
  - Custom CRF values
- **Source Matching**: Quick buttons to match source video settings
- **Estimated Bitrate Calculator**: Real-time calculation of target video bitrate

## Prerequisites

### FFmpeg Installation

This application requires FFmpeg to be installed on your system:

**Windows:**
```bash
winget install FFmpeg
```
Or with Chocolatey:
```bash
choco install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

### Python Requirements

- Python 3.7 or higher
- pip (Python package installer)

## Installation

1. **Clone or download this repository**

2. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

3. **Verify FFmpeg installation:**
```bash
ffmpeg -version
```

## Usage

1. **Start the Flask server:**
```bash
python app.py
```

2. **Open your browser and navigate to:**
```
http://localhost:5000
```

3. **Compress your video:**
   - Drag and drop a video file or click to browse
   - Adjust settings in the tabs:
     - **File Size**: Set target output size
     - **Video**: Configure resolution and frame rate
     - **Audio**: Set audio bitrate or mute
     - **Encoder**: Choose preset, CRF, and tune options
   - Click "Compress Video"
   - Wait for processing to complete
   - Download your compressed video

## Configuration

### Tab Options

**File Size Tab:**
- **Target Size**: Desired output file size in MB
- **Match Source Size**: Use the original file size as target
- **Estimated Bitrate**: Auto-calculated video bitrate based on settings

**Video Tab:**
- **Resolution**: Width and height (automatically adjusted to even numbers)
- **Frame Rate**: Target FPS
- **Use Source Settings**: Load original video parameters

**Audio Tab:**
- **Mute Audio**: Remove audio track completely
- **Audio Bitrate**: Audio quality in kbps
- **Match Source Audio**: Use original audio bitrate

**Encoder Tab:**
- **Preset**: Encoding speed/quality tradeoff
  - `ultrafast`: Fastest encoding, larger files
  - `fast`: Good balance for quick processing
  - `medium`: Default, balanced option
  - `slow`: Better compression, slower encoding
- **CRF**: Constant Rate Factor (0-51)
  - Lower values = better quality, larger files
  - 18-28 is typical range
  - Leave empty to use file size targeting
- **Tune**: Optimize for content type
  - `film`: Live-action content
  - `animation`: Animated content
  - `grain`: Grainy/film grain content
  - `stillimage`: Slideshow-style videos

## Technical Details

### How It Works

1. **File Upload**: Videos are uploaded to a temporary directory
2. **FFprobe Analysis**: Video metadata is extracted using FFprobe
3. **Bitrate Calculation**: Target video bitrate is calculated based on:
   - Target file size
   - Video duration
   - Audio bitrate
   - 3% safety margin
4. **FFmpeg Encoding**: Video is re-encoded with specified parameters
5. **Progress Tracking**: FFmpeg output is parsed for real-time progress
6. **Download**: Compressed video is made available for download

### File Processing

- Videos are processed using H.264 (libx264) codec
- Audio is encoded with AAC
- Dimensions are automatically adjusted to even numbers (required by H.264)
- Temporary files are stored in the system temp directory

### API Endpoints

- `GET /`: Main application interface
- `GET /check_ffmpeg`: Verify FFmpeg installation
- `POST /upload`: Upload video file and extract metadata
- `POST /compress`: Start compression job
- `GET /status/<job_id>`: Get compression progress
- `GET /download/<job_id>`: Download compressed video

## Troubleshooting

### FFmpeg Not Found
If you see "FFmpeg is not installed" error:
1. Verify FFmpeg is installed: `ffmpeg -version`
2. Ensure FFmpeg is in your system PATH
3. Restart the application after installing FFmpeg

### Upload Fails
- Check file is a valid video format (MP4, AVI, MKV, MOV, etc.)
- Ensure sufficient disk space in temp directory
- Maximum file size is 5GB

### Compression Fails
- Verify all required fields are filled (width, height, fps)
- Ensure target size is reasonable (not too small)
- Check FFmpeg console output in terminal for detailed errors

### Target Size Too Small
If you see "Target size too small" error:
- Increase the target file size
- Reduce video resolution or frame rate
- Use lower audio bitrate or mute audio
- Consider using CRF mode instead

## Performance Tips

1. **Preset Selection**:
   - Use `ultrafast` for quick previews
   - Use `medium` or `slow` for final output
   - Slower presets give better compression but take longer

2. **CRF vs File Size**:
   - Use CRF for quality-focused compression
   - Use file size targeting when output size matters

3. **Resolution Scaling**:
   - Reducing resolution significantly decreases file size
   - Maintain aspect ratio for best results

## Browser Compatibility

- Chrome/Edge: Full support
- Firefox: Full support
- Safari: Full support
- Mobile browsers: Supported (responsive design)

## Security Notes

- Files are stored in temporary directory
- No authentication required (suitable for local/trusted networks only)
- Consider adding authentication for production use
- Clean up temporary files periodically

## License

This project is provided as-is for educational and personal use.

## Credits

Built with:
- Flask (Python web framework)
- FFmpeg (video processing)
- Orbitron & Overpass fonts (Google Fonts)
- Modern CSS animations and effects
