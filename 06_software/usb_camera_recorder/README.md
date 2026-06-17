# USB Camera Recorder

Small Windows GUI for recording the `USB Camera` device as MP4 data for the PC-side vision prototype.

Clicking **Start Recording** opens a live preview window and starts saving the MP4 at the same time. The preview copies the camera's original MJPEG frames from the same FFmpeg stream as the recording, because this camera cannot reliably be opened by two programs at once.

## Output

Recordings are saved by default to:

```text
D:\mywork\code\embedded-contest-project\08_media\camera_data
```

File names use the local start timestamp:

```text
usbcam_YYYYMMDD_HHMMSS.mp4
```

Each recording also writes an FFmpeg log next to the video:

```text
usbcam_YYYYMMDD_HHMMSS.ffmpeg.log
```

## Run From Source

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\usb_camera_recorder
py usb_camera_recorder.py
```

Default capture settings:

```text
Device: USB Camera
Resolution: 1280x720
FPS: 30
Codec: H.264 MP4, CRF 18, preset veryfast
Preview: enabled, original MJPEG frame quality
```

Use the resolution dropdown to switch to `1920x1080` or `2560x1440` when detail matters. For smoother capture and lower CPU load, keep `1280x720`.

Keep the preview window open while recording. Use the recorder's **Stop Recording** button to stop cleanly and finalize the MP4.

## Build EXE

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\usb_camera_recorder
py -m PyInstaller --noconfirm --clean --noconsole --name "USB Camera Recorder" usb_camera_recorder.py
```

For a single-file executable:

```powershell
py -m PyInstaller --noconfirm --clean --noconsole --onefile --distpath dist_onefile --name "USB Camera Recorder" usb_camera_recorder.py
```

The single-file executable is created at:

```text
D:\mywork\code\embedded-contest-project\06_software\usb_camera_recorder\dist_onefile\USB Camera Recorder.exe
```

Note: this tool requests the selected resolution at `30` FPS from the camera. The actual saved FPS can be lower if the camera/driver reduces frame delivery, for example because of long exposure in dim light.

## Tests

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\usb_camera_recorder
py -m unittest discover -s tests -v
```
