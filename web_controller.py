#!/usr/bin/env python3
"""
Web-based controller for X Clock
Provides a simple UI to send OSC commands to the clock
"""
import argparse
import socket

from flask import Flask, jsonify, render_template_string, request
from pythonosc import udp_client

app = Flask(__name__)
osc_client = None
osc_config = {}


def get_local_ip():
    """Get the non-loopback local IP address"""
    try:
        # Create a socket to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>X Clock Controller</title>
    <style>
        body {
            font-family: 'Courier New', monospace;
            max-width: 800px;
            margin: 40px auto;
            padding: 20px;
            background: #1a1a1a;
            color: #29B6F6;
        }
        h1 {
            text-align: center;
            border-bottom: 2px solid #29B6F6;
            padding-bottom: 10px;
        }
        .section {
            margin: 20px 0;
            padding: 15px;
            border: 1px solid #29B6F6;
            border-radius: 5px;
        }
        .section h2 {
            margin-top: 0;
            font-size: 1.2em;
        }
        label {
            display: inline-block;
            width: 150px;
            margin: 5px 0;
        }
        input[type="text"], input[type="number"] {
            background: #2a2a2a;
            border: 1px solid #29B6F6;
            color: #29B6F6;
            padding: 5px;
            margin: 5px;
        }
        input[type="color"] {
            background: #2a2a2a;
            border: 1px solid #29B6F6;
            padding: 2px;
            margin: 5px;
            height: 35px;
            width: 60px;
            cursor: pointer;
        }
        button {
            background: #29B6F6;
            color: #1a1a1a;
            border: none;
            padding: 10px 20px;
            cursor: pointer;
            margin: 5px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
        }
        button:hover {
            background: #4fc3f7;
        }
        .status {
            position: fixed;
            top: 10px;
            right: 10px;
            padding: 10px;
            background: #2a2a2a;
            border: 1px solid #29B6F6;
            border-radius: 5px;
            display: none;
        }
        .status.show {
            display: block;
        }
        .osc-info {
            background: #2a2a2a;
            padding: 10px;
            margin-bottom: 20px;
            border: 1px solid #29B6F6;
            border-radius: 5px;
            text-align: center;
        }
        .command-log {
            max-height: 300px;
            overflow-y: auto;
            background: #0a0a0a;
            padding: 10px;
            font-size: 0.9em;
            border-radius: 3px;
        }
        .log-entry {
            padding: 5px;
            border-bottom: 1px solid #1a1a1a;
            font-family: 'Courier New', monospace;
        }
        .log-entry:last-child {
            border-bottom: none;
        }
        .log-time {
            color: #666;
            margin-right: 10px;
        }
        .log-command {
            color: #29B6F6;
        }
        .preview-container {
            text-align: center;
            background: #0a0a0a;
            padding: 15px;
            border-radius: 5px;
        }
        .preview-container img {
            border: 2px solid #29B6F6;
            image-rendering: pixelated;
            image-rendering: -moz-crisp-edges;
            image-rendering: crisp-edges;
        }
        .preview-controls {
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <h1>X CLOCK CONTROLLER</h1>
    <div class="status" id="status"></div>

    <div class="osc-info">
        <strong>OSC Target:</strong> {{ osc_display }}
        <span style="margin-left: 20px;">|</span>
        <strong style="margin-left: 20px;">Preview:</strong> <span id="preview-status">Idle</span>
    </div>

    <div class="section">
        <h2>Live Preview</h2>
        <div style="margin-bottom: 10px;">
            <button onclick="togglePreview()" id="togglePreviewBtn">Show Preview</button>
            <span style="margin-left: 10px; font-size: 0.9em; color: #666;">
                (Preview adds CPU load to the clock)
            </span>
        </div>
        <div class="preview-container" id="previewContainer" style="display: none;">
            <img id="clockPreview" alt="Clock display" onerror="handleStreamError()" onload="handleStreamLoad()">
        </div>
    </div>

    <div class="section">
        <h2>Command Log</h2>
        <button onclick="clearLog()" style="background: #666; padding: 5px 10px;">Clear Log</button>
        <div class="command-log" id="commandLog">
            <div style="color: #666; text-align: center;">No commands sent yet</div>
        </div>
    </div>

    <div class="section">
        <h2>Appearance</h2>
        <div>
            <label>Brightness (0-100):</label>
            <input type="number" id="brightness" min="0" max="100" value="100">
            <label>Fade Time (sec):</label>
            <input type="number" id="fadetime" min="0" step="0.1" value="0">
            <button onclick="sendBrightness()">Set Brightness</button>
        </div>
        <div>
            <label>Text Color:</label>
            <input type="color" id="colorPicker" value="#29B6F6" onchange="updateColorText('color', 'colorPicker')">
            <input type="text" id="color" value="29B6F6" placeholder="hex or name" style="width: 120px;" onchange="updateColorPicker('color', 'colorPicker')">
            <button onclick="sendColor()">Set Color</button>
        </div>
        <div>
            <label>X Color:</label>
            <input type="color" id="xcolorPicker" value="#29B6F6" onchange="updateColorText('xcolor', 'xcolorPicker')">
            <input type="text" id="xcolor" value="29B6F6" placeholder="hex or name" style="width: 120px;" onchange="updateColorPicker('xcolor', 'xcolorPicker')">
            <button onclick="sendXColor()">Set X Color</button>
        </div>
        <div>
            <label>Background:</label>
            <input type="color" id="bgPicker" value="#000000" onchange="updateColorText('bg', 'bgPicker')">
            <input type="text" id="bg" value="000000" placeholder="hex or name" style="width: 120px;" onchange="updateColorPicker('bg', 'bgPicker')">
            <button onclick="sendBG()">Set Background</button>
        </div>
    </div>

    <div class="section">
        <h2>Time Control</h2>
        <div>
            <label>Hour (0-23):</label>
            <input type="number" id="hour" min="0" max="23" value="12">
            <label>Minute (0-59):</label>
            <input type="number" id="minute" min="0" max="59" value="0">
            <button onclick="sendTime()">Set Time</button>
        </div>
        <div>
            <label>Increment (minutes):</label>
            <input type="number" id="increment" value="5">
            <button onclick="sendIncrement()">Increment Time</button>
        </div>
        <div>
            <button onclick="sendCommand('/timenow')">Set to Current Time</button>
            <label>Freeze:</label>
            <button onclick="sendCommand('/freeze', [1])">Freeze</button>
            <button onclick="sendCommand('/freeze', [0])">Unfreeze</button>
        </div>
    </div>

    <div class="section">
        <h2>Time Dilation</h2>
        <label>Factor:</label>
        <input type="number" id="dilation" step="0.1" value="1.0">
        <button onclick="sendTimeDilation()">Set Time Dilation</button>
        <div style="margin-top: 10px; font-size: 0.9em;">
            Examples: 1.0=normal, 2.0=2x speed, 0.5=half speed, -1.0=reverse
        </div>
    </div>

    <div class="section">
        <h2>Blinking</h2>
        <div>
            <label>Blink Dots:</label>
            <button onclick="sendCommand('/blink_dots', [1])">Enable</button>
            <button onclick="sendCommand('/blink_dots', [0])">Disable</button>
        </div>
        <div>
            <label>Blink All:</label>
            <button onclick="sendCommand('/blink_all', [1])">Enable</button>
            <button onclick="sendCommand('/blink_all', [0])">Disable</button>
        </div>
    </div>

    <div class="section">
        <h2>Glitch Effects</h2>
        <div style="margin-bottom: 15px; padding: 10px; background: #0a0a0a; border-radius: 3px; font-size: 0.9em;">
            <strong>Frequency:</strong> Probability out of 10,000 that effect triggers on any given frame.<br>
            Example: 100 = ~1% chance per frame, 1000 = ~10% chance per frame. Set to 0 to disable.
        </div>

        <h3 style="font-size: 1em; margin: 15px 0 10px 0; border-bottom: 1px solid #29B6F6;">Visual Glitch (Screen Distortion)</h3>
        <div>
            <label>Frequency (0-10000):</label>
            <input type="number" id="glitchfreq" min="0" max="10000" value="0" style="width: 100px;">
            <button onclick="sendRandomGlitch()">Enable</button>
            <button onclick="sendCommand('/random_glitch', [0])" style="background: #666;">Disable</button>
        </div>

        <h3 style="font-size: 1em; margin: 15px 0 10px 0; border-bottom: 1px solid #29B6F6;">Random X Glitch (Replace Numbers with X)</h3>
        <div style="margin-bottom: 10px;">
            <label>Frequency (0-10000):</label>
            <input type="number" id="xglitchfreq" min="0" max="10000" value="0" style="width: 100px;">
        </div>
        <div style="margin-bottom: 10px;">
            <label>Digits to Replace:</label>
            <input type="number" id="xglitchnum" min="1" max="4" value="1" style="width: 60px;">
            <label style="width: auto; margin-left: 20px;">Duration (frames):</label>
            <input type="number" id="xglitchframes" min="1" value="1" style="width: 60px;">
        </div>
        <div>
            <button onclick="sendRandomXGlitch()">Enable</button>
            <button onclick="sendCommand('/random_x_glitch', [0])" style="background: #666;">Disable</button>
        </div>

        <h3 style="font-size: 1em; margin: 15px 0 10px 0; border-bottom: 1px solid #29B6F6;">Single X Glitch (Trigger Once)</h3>
        <div style="margin-bottom: 10px;">
            <label>Digits to Replace:</label>
            <input type="number" id="singlexnum" min="1" max="4" value="1" style="width: 60px;">
            <label style="width: auto; margin-left: 20px;">Duration (frames):</label>
            <input type="number" id="singlexframes" min="1" value="1" style="width: 60px;">
        </div>
        <div>
            <button onclick="sendSingleXGlitch()">Trigger Now</button>
        </div>
    </div>

    <div class="section">
        <h2>X Positions</h2>
        <label>Positions (4 chars):</label>
        <input type="text" id="xpositions" maxlength="4" value="0000" placeholder="e.g. X0X0">
        <button onclick="sendXPositions()">Set X Positions</button>
        <div style="margin-top: 10px; font-size: 0.9em;">
            Use 'X' to show X in that position, any other char to show time digit
        </div>
    </div>

    <div class="section">
        <h2>Special Effects</h2>
        <div>
            <label>Glitch To Hour:</label>
            <input type="number" id="glitchhour" min="0" max="23" value="12">
            <label>Minute:</label>
            <input type="number" id="glitchminute" min="0" max="59" value="0">
            <label>Frames:</label>
            <input type="number" id="glitchframes" min="1" value="5">
            <button onclick="sendGlitchTo()">Glitch To Time</button>
        </div>
        <div>
            <label>Fadesnap Hour:</label>
            <input type="number" id="fadesnaphour" min="0" max="23" value="12">
            <label>Minute:</label>
            <input type="number" id="fadesnapminute" min="0" max="59" value="0">
            <label>Duration (sec):</label>
            <input type="number" id="fadesnapduration" min="0" step="0.1" value="1">
            <button onclick="sendFadeSnap()">Fadesnap</button>
        </div>
    </div>

    <div class="section">
        <h2>Reset</h2>
        <button onclick="sendCommand('/normal')" style="background: #f44336;">Reset to Normal</button>
    </div>

    <div class="section">
        <h2>Configuration</h2>
        <div>
            <label>Display Custom Text:</label>
            <input type="text" id="displayText" placeholder="Enter text to scroll">
            <button onclick="sendCommand('/display_text', [document.getElementById('displayText').value])">Display</button>
            <button onclick="sendCommand('/display_text', [])">Disable</button>
            <div style="margin-top: 5px; font-size: 0.9em; color: #666;">
                (Scrolls custom text across display. Disable returns to normal time display)
            </div>
        </div>
        <div>
            <label>Show IP Address:</label>
            <button onclick="sendCommand('/showip', [1])">Enable</button>
            <button onclick="sendCommand('/showip', [0])">Disable</button>
            <div style="margin-top: 5px; font-size: 0.9em; color: #666;">
                (Scrolls IP address across display instead of time)
            </div>
        </div>
    </div>

    <script>
        let previewActive = false;
        const streamUrl = '{{ clock_url }}/stream';

        function togglePreview() {
            const btn = document.getElementById('togglePreviewBtn');
            const container = document.getElementById('previewContainer');
            const img = document.getElementById('clockPreview');
            const status = document.getElementById('preview-status');

            previewActive = !previewActive;

            if (previewActive) {
                // Start stream
                img.src = streamUrl;
                container.style.display = 'block';
                btn.textContent = 'Hide Preview';
                status.textContent = 'Connecting...';
                status.style.color = '#29B6F6';
            } else {
                // Stop stream
                img.src = '';
                container.style.display = 'none';
                btn.textContent = 'Show Preview';
                status.textContent = 'Idle';
                status.style.color = '#666';
            }
        }

        function handleStreamError() {
            if (!previewActive) return;
            const status = document.getElementById('preview-status');
            status.textContent = 'Disconnected';
            status.style.color = '#f44336';
        }

        function handleStreamLoad() {
            if (!previewActive) return;
            const status = document.getElementById('preview-status');
            status.textContent = 'Streaming';
            status.style.color = '#4caf50';
        }

        function updateColorText(textId, pickerId) {
            const picker = document.getElementById(pickerId);
            const text = document.getElementById(textId);
            // Remove # from hex color for consistency with OSC format
            text.value = picker.value.substring(1);
        }

        function updateColorPicker(textId, pickerId) {
            const text = document.getElementById(textId);
            const picker = document.getElementById(pickerId);
            let colorValue = text.value.trim();

            // Try to convert to valid hex for picker
            if (colorValue.length === 6 && /^[0-9A-Fa-f]{6}$/.test(colorValue)) {
                picker.value = '#' + colorValue;
            }
            // If it's a named color, we can't easily convert it for the picker
            // so just leave the picker as-is
        }

        // Load status and populate UI on page load
        window.addEventListener('load', () => {
            loadStatus();
        });

        function loadStatus() {
            fetch('{{ clock_url }}/status')
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        console.warn('Could not load status:', data.error);
                        return;
                    }

                    // Populate time
                    if (data.time) {
                        document.getElementById('hour').value = data.time.hour;
                        document.getElementById('minute').value = data.time.minute;
                    }

                    // Populate appearance
                    if (data.appearance) {
                        document.getElementById('brightness').value = data.appearance.brightness;
                        document.getElementById('color').value = data.appearance.text_color;
                        updateColorPicker('color', 'colorPicker');
                        document.getElementById('xcolor').value = data.appearance.x_color;
                        updateColorPicker('xcolor', 'xcolorPicker');
                        document.getElementById('bg').value = data.appearance.background;
                        updateColorPicker('bg', 'bgPicker');
                    }

                    // Populate effects
                    if (data.effects) {
                        document.getElementById('dilation').value = data.effects.time_dilation;
                    }

                    // Populate glitches
                    if (data.glitches) {
                        document.getElementById('glitchfreq').value = data.glitches.visual_glitch_freq;
                        document.getElementById('xglitchfreq').value = data.glitches.x_glitch_freq;
                        document.getElementById('xglitchnum').value = data.glitches.x_glitch_number;
                        document.getElementById('xglitchframes').value = data.glitches.x_glitch_frames;
                    }

                    console.log('Status loaded successfully');
                })
                .catch(error => {
                    console.warn('Could not load status:', error);
                });
        }

        function showStatus(message, isError = false) {
            const status = document.getElementById('status');
            status.textContent = message;
            status.style.borderColor = isError ? '#f44336' : '#4caf50';
            status.classList.add('show');
            setTimeout(() => status.classList.remove('show'), 2000);
        }

        function formatQLabOSC(command, args) {
            // Format OSC message in QLab format: address arg1 arg2 arg3
            // String arguments with spaces need quotes, numbers don't
            const formattedArgs = args.map(arg => {
                if (typeof arg === 'string') {
                    // Add quotes if string contains spaces or is non-numeric
                    return arg.includes(' ') ? `"${arg}"` : arg;
                }
                return arg;
            });

            return formattedArgs.length > 0
                ? `${command} ${formattedArgs.join(' ')}`
                : command;
        }

        function addLogEntry(command, args) {
            const log = document.getElementById('commandLog');

            // Clear placeholder message if present
            if (log.children.length === 1 && log.children[0].textContent === 'No commands sent yet') {
                log.innerHTML = '';
            }

            const entry = document.createElement('div');
            entry.className = 'log-entry';

            const time = new Date().toLocaleTimeString();
            const qlabFormat = formatQLabOSC(command, args);

            entry.innerHTML = `<span class="log-time">[${time}]</span><span class="log-command">${qlabFormat}</span>`;

            // Add to bottom instead of top
            log.appendChild(entry);

            // Auto-scroll to bottom
            log.scrollTop = log.scrollHeight;

            // Limit log to 100 entries, remove from top
            while (log.children.length > 100) {
                log.removeChild(log.firstChild);
            }
        }

        function clearLog() {
            const log = document.getElementById('commandLog');
            log.innerHTML = '<div style="color: #666; text-align: center;">No commands sent yet</div>';
        }

        async function sendCommand(command, args = []) {
            try {
                const response = await fetch('/osc', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({command, args})
                });
                const result = await response.json();
                if (result.status === 'ok') {
                    showStatus('Command sent: ' + command);
                    addLogEntry(command, args);
                } else {
                    showStatus('Error: ' + result.message, true);
                }
            } catch (error) {
                showStatus('Network error', true);
            }
        }

        function sendTime() {
            const hour = parseInt(document.getElementById('hour').value);
            const minute = parseInt(document.getElementById('minute').value);
            sendCommand('/time', [hour, minute]);
        }

        function sendIncrement() {
            const increment = parseInt(document.getElementById('increment').value);
            sendCommand('/increment_time', [increment]);
        }

        function sendTimeDilation() {
            const factor = parseFloat(document.getElementById('dilation').value);
            sendCommand('/time_dilation', [factor]);
        }

        function sendBrightness() {
            const brightness = parseInt(document.getElementById('brightness').value);
            const fadetime = parseFloat(document.getElementById('fadetime').value);
            sendCommand('/brightness', [brightness, fadetime]);
        }

        function sendColor() {
            const color = document.getElementById('color').value;
            sendCommand('/color', [color]);
        }

        function sendXColor() {
            const color = document.getElementById('xcolor').value;
            sendCommand('/x_color', [color]);
        }

        function sendBG() {
            const color = document.getElementById('bg').value;
            sendCommand('/bg', [color]);
        }

        function sendRandomGlitch() {
            const freq = parseInt(document.getElementById('glitchfreq').value);
            sendCommand('/random_glitch', [freq]);
        }

        function sendRandomXGlitch() {
            const freq = parseInt(document.getElementById('xglitchfreq').value);
            const num = parseInt(document.getElementById('xglitchnum').value);
            const frames = parseInt(document.getElementById('xglitchframes').value);
            sendCommand('/random_x_glitch', [freq, num, frames]);
        }

        function sendSingleXGlitch() {
            const num = parseInt(document.getElementById('singlexnum').value);
            const frames = parseInt(document.getElementById('singlexframes').value);
            sendCommand('/single_x_glitch', [num, frames]);
        }

        function sendXPositions() {
            const positions = document.getElementById('xpositions').value;
            sendCommand('/x_positions', [positions]);
        }

        function sendGlitchTo() {
            const hour = parseInt(document.getElementById('glitchhour').value);
            const minute = parseInt(document.getElementById('glitchminute').value);
            const frames = parseInt(document.getElementById('glitchframes').value);
            sendCommand('/glitch_to', [hour, minute, frames]);
        }

        function sendFadeSnap() {
            const hour = parseInt(document.getElementById('fadesnaphour').value);
            const minute = parseInt(document.getElementById('fadesnapminute').value);
            const duration = parseFloat(document.getElementById('fadesnapduration').value);
            sendCommand('/fadesnap', [hour, minute, duration]);
        }
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        osc_display=osc_config["display"],
        clock_url=osc_config["clock_url"],
    )


@app.route("/osc", methods=["POST"])
def osc():
    try:
        data = request.json
        command = data.get("command")
        args = data.get("args", [])

        if not command:
            return jsonify({"status": "error", "message": "No command specified"}), 400

        # Send OSC message
        osc_client.send_message(command, args)

        return jsonify({"status": "ok", "command": command, "args": args})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def main():
    parser = argparse.ArgumentParser(description="Web controller for X Clock")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind web server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to bind web server to (default: 5000)",
    )
    parser.add_argument(
        "--osc-host", default="127.0.0.1", help="OSC server host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--osc-port", type=int, default=1337, help="OSC server port (default: 1337)"
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=8080,
        help="HTTP preview port on clock server (default: 8080)",
    )

    args = parser.parse_args()

    global osc_client, osc_config
    osc_client = udp_client.SimpleUDPClient(args.osc_host, args.osc_port)

    # Determine OSC display string and stream URL
    if args.osc_host in ("127.0.0.1", "localhost"):
        local_ip = get_local_ip()
        osc_config["display"] = f"{local_ip}:{args.osc_port}"
        # For localhost, use the actual IP so browser can connect
        osc_config["clock_url"] = f"http://{local_ip}:{args.http_port}"
    else:
        osc_config["display"] = f"{args.osc_host}:{args.osc_port}"
        osc_config["clock_url"] = f"http://{args.osc_host}:{args.http_port}"

    print(f"X Clock Web Controller")
    print(f"Web UI: http://{args.host}:{args.port}")
    print(f"OSC Target: {osc_config['display']}")
    print(f"Clock URL: {osc_config['clock_url']}")

    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
