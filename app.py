# Importing necessary modules and packages
import json
import re
import threading
from flask import Flask, render_template, jsonify, request, send_from_directory, url_for, Response

import db
import requests
import time
import os
from werkzeug.utils import secure_filename

# Creating a Flask application instance
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Default Values
app.brightness = 1
app.delSegments = ""
app.timeout = 5
app.standbyColor = "#00ff00"
app.locateColor = "#00ff00"
app.config['UPLOAD_FOLDER'] = './images'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB upload limit
app.previous_positions = {}  # last located LED positions, per ESP IP
app.off_timers = {}  # pending turn-off timers, per ESP IP
app.request_amount = 0

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


@app.route('/proxy-image', methods=['GET'])
def proxy_image():
    image_url = request.args.get('url', '')
    if not image_url.startswith(('http://', 'https://')):
        return jsonify({'error': 'Invalid URL'}), 400

    try:
        response = requests.get(image_url, timeout=5)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error proxying image: {e}")
        return jsonify({'error': 'Could not fetch image'}), 502

    content_type = response.headers.get('Content-Type', '')
    if not content_type.startswith('image/'):
        return jsonify({'error': 'URL does not point to an image'}), 400

    return Response(response.content, content_type=content_type)


# Route to Favicon
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.root_path, 'favicon.ico', mimetype='image/vnd.microsoft.icon')


# Route to the home page of the web application
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/images/<name>')
def download_image(name):
    return send_from_directory(app.config["UPLOAD_FOLDER"], name)


@app.route('/upload', methods=['POST'])
def upload_file():
    # check if the post request has the file part
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    # If the user does not select a file, the browser submits an
    # empty file without a filename.
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if not filename or extension not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({'error': 'File type not allowed'}), 400

    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return url_for('download_image', name=filename)


@app.route('/api/tags', methods=['GET', 'POST'])
def tags():
    if request.method == 'GET':
        try:
            tag_data = db.get_all_tags()  # Fetch ESP data from the database
            return jsonify(tag_data), 200
        except Exception as e:
            print(f"Error fetching Tag data: {e}")  # Log the error for debugging
            return jsonify({"error": "An error occurred fetching Tag data"}), 500


def get_unique_ips_from_database():
    # Get all items from the database
    ips = db.read_esp()
    # Create a set to store unique IP addresses
    unique_ips = set()
    # Iterate through the items and extract unique IPs
    for ip in ips:
        ip = ip.get('esp_ip')
        if ip:
            unique_ips.add(ip)
    # Convert the set of unique IPs back to a list (if needed)
    unique_ips_list = list(unique_ips)

    return unique_ips_list


def is_valid_url_or_ip(input_str):
    ip_pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")  # Simple IP address regex
    url_pattern = re.compile(r"([a-zA-Z0-9-]+)\.([a-zA-Z]{2,})")

    if ip_pattern.match(input_str):
        return True

    return bool(url_pattern.match(input_str))


def set_global_settings():
    settings = db.read_settings()

    if settings:
        app.brightness = settings['brightness'] / 100
        app.timeout = settings['timeout']

        colors = settings.get('colors')
        # Assign colors
        if isinstance(colors, list) and len(colors) >= 2:
            app.standbyColor = colors[0]
            app.locateColor = colors[1]


@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'GET':
        # If the request method is GET, read data from the database and return as JSON
        return jsonify(db.read_settings())
    elif request.method == 'POST':
        db.update_settings(request.get_json())  # Update settings in the database
        return jsonify({'success': True})


@app.route('/api/esp/', methods=['GET', 'POST'])
def esps():
    if request.method == 'GET':
        try:
            esps_data = db.read_esp()  # Fetch ESP data from the database
            return jsonify(esps_data), 200
        except Exception as e:
            print(f"Error fetching ESP data: {e}")  # Log the error for debugging
            return jsonify({"error": "An error occurred fetching ESP data"}), 500

    elif request.method == 'POST':
        try:
            esp_data = request.get_json()
            if not esp_data:
                return jsonify({"error": "No data provided"}), 400

            id = db.write_esp_settings(esp_data)
            if id is None:
                raise ValueError("Failed to write ESP settings")

            esp_data['id'] = id
            return jsonify(esp_data), 201
        except Exception as e:
            print(f"Error on writing ESP data: {e}")  # Log the error
            return jsonify({"error": "An error occurred writing ESP data"}), 500

    else:
        return jsonify({"error": "Method not allowed"}), 405


@app.route('/api/esp/<id>', methods=['GET', 'PUT', 'DELETE'])
def handle_esp(id):
    if request.method == 'GET':
        esp_data = db.get_esp_settings_by_ip(id)
        if esp_data is not None:
            return jsonify(esp_data)
        else:
            return jsonify({'error': 'ESP not found'}), 404

    elif request.method == 'PUT':
        esp_data = request.get_json()
        db.update_esp_settings(id, esp_data)
        return jsonify({'success': True})

    elif request.method == 'DELETE':
        db.delete_esp_settings(id)
        return jsonify({'success': True})


# Route to handle GET and POST requests for items
@app.route('/api/items', methods=['GET', 'POST'])
def items():
    if request.method == 'GET':
        items = db.read_items()
        return jsonify(items)
    elif request.method == 'POST':
        item = request.get_json()
        if not item or not str(item.get('name', '')).strip():
            return jsonify({'error': 'Name required'}), 400
        id = db.write_item(item)
        item['id'] = id
        return jsonify(item)


# Route to handle GET, PUT, DELETE requests for a specific item
@app.route('/api/items/<id>', methods=['GET', 'PUT', 'DELETE', 'POST'])
def item(id):
    item = db.get_item(id)
    if item is None:
        return jsonify({'error': 'Item not found'}), 404

    if request.method == 'GET':
        return jsonify(item)

    elif request.method == 'PUT':
        if request.headers.get('Update-Quantity') == 'true':
            db.update_item_quantity(id, request.get_json())
        elif request.headers.get('Update-Image') == 'true':
            db.update_item_image(id, request.get_json())
        else:
            db.update_item(id, request.get_json())
        return jsonify(db.get_item(id))

    elif request.method == 'DELETE':
        db.delete_item(id)
        return jsonify({'success': True})
    elif request.method == 'POST':

        if request.form.get('action') == 'locate':
            if is_valid_url_or_ip(item['ip']):
                ip = item['ip']
            else:
                ip = db.get_ip_by_name(item['ip'])
            esp = db.get_esp_settings_by_ip(ip)
            light(item['position'], ip, esp, item['quantity'])

            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Invalid action'}), 400


def send_request(target_ip, data, timeout=2.0):
    url = f"http://{target_ip}/json/state"

    try:
        response = requests.post(url, json=data, timeout=timeout)
        # Check for successful response, and handle accordingly

        if response.status_code == 200:
            # Success
            app.request_amount += 1
        else:
            # Handle other status codes (e.g., 404, 500, etc.) as needed
            print(f"Request failed with status code {response.status_code}")
    except requests.RequestException as e:
        # Covers connection errors, timeouts and other request failures
        print(f"Request to {target_ip} failed: {e}")


def get_total_leds(ip):
    try:
        response = requests.get(f"http://{ip}/json/info", timeout=2)
        response.raise_for_status()
        info = response.json()
        return info['leds']['count']
    except requests.RequestException as e:
        print(f"Error fetching total LEDs: {e}")
        return 1000  # Default value if the request fails


def cancel_off_timer(ip=None):
    # Cancel the pending turn-off timer for one ESP, or for all ESPs
    ips = [ip] if ip else list(app.off_timers.keys())
    for key in ips:
        timer = app.off_timers.pop(key, None)
        if timer:
            timer.cancel()


def set_leds(led_indices, color, off_color, ip, testing=False):
    # Get the total number of LEDs from the WLED API
    total_leds = get_total_leds(ip)

    # A new locate action supersedes any pending turn-off for this ESP
    cancel_off_timer(ip)

    # Clear existing segments if they exist
    if app.delSegments:
        off_data = {"on": False, "bri": 0, "transition": 0, "mainseg": 0, "seg": []}
        send_request(ip, off_data)
        time.sleep(0.3)
    else:
        # Turn off all LEDs with the off_color
        payload = {
            "on": False,
            "seg": {"i": []}
        }
        send_request(ip, payload)
        time.sleep(0.3)

    def build_off_payload():
        # Payload that resets all LEDs to the standby color
        payload = {
            "on": True,
            "seg": {"i": []}
        }
        for i in range(total_leds):
            payload["seg"]["i"].extend([i, off_color[1:]])
        return payload

    # Convert the LED indices from a string to a list of integers if necessary
    if isinstance(led_indices, str):
        led_indices_new = list(map(int, led_indices.split(',')))
    else:
        led_indices_new = list(map(int, led_indices))

    # Check if the new positions are different from the previous ones
    toggled_off = False
    if app.previous_positions.get(ip) != led_indices_new:
        # Initialize payload for turning on LEDs with the desired color
        on_payload = {
            "on": True,
            "seg": {"i": []}
        }

        # Light up the current LEDs with the desired color
        for i in led_indices_new:
            on_payload["seg"]["i"].extend([i, color[1:]])

        # Send the API request to set the colors of the LEDs
        send_request(ip, on_payload)

        # Update the previous positions to the current ones
        app.previous_positions[ip] = led_indices_new
    else:
        # If the positions are the same, turn off all LEDs
        send_request(ip, build_off_payload())
        app.previous_positions.pop(ip, None)
        toggled_off = True

    # Schedule turning the LEDs off after the timeout, without blocking the request
    if testing:
        time.sleep(app.timeout + 3)  # Ensure a minimum delay during testing
    elif app.timeout > 0 and not toggled_off:
        def turn_off():
            send_request(ip, build_off_payload())
            app.previous_positions.pop(ip, None)
            app.off_timers.pop(ip, None)

        timer = threading.Timer(app.timeout, turn_off)
        timer.daemon = True
        app.off_timers[ip] = timer
        timer.start()

    app.delSegments = True


def light(positions, ip, esp, quantity=1, testing=False):
    # Set global settings
    set_global_settings()
    positions_list = position_optimization(sorted(json.loads(positions)), esp)
    if testing:
        set_leds(positions_list, app.locateColor, app.standbyColor, ip, testing)
    elif quantity <= 0:
        set_leds(positions_list, "#FF0000", app.standbyColor, ip, testing)
    else:
        set_leds(positions_list, app.locateColor, app.standbyColor, ip, testing)


def position_optimization(positions, esp):
    segments = []
    rows = esp['rows']
    columns = esp['cols']
    start_y = esp['start_top'].lower()
    start_x = esp['start_left'].lower()
    serpentine_direction = esp['serpentine_direction'].lower()

    if start_x == "1":
        start_x = "right"

    if serpentine_direction == "1":
        serpentine_direction = "vertical"

    for pos in positions:
        i = pos - 1

        if serpentine_direction == "horizontal":
            # Handle horizontal serpentine direction
            row = i // columns
            column = i % columns if row % 2 == 0 else columns - 1 - (i % columns)
        else:  # serpentine_direction == "vertical"
            # Handle vertical serpentine direction
            column = i // rows
            row = i % rows if column % 2 == 0 else rows - 1 - (i % rows)

        # Adjust for starting positions
        if start_x == "right":
            column = columns - 1 - column
        if start_y == "bottom":
            row = rows - 1 - row

        # Calculate the LED number
        if row % 2 == 0:
            # Even rows - normal left to right
            led_number = row * columns + column
        else:
            # Odd rows - right to left
            led_number = row * columns + (columns - 1 - column)
        # Append the last segment
        segments.append(led_number)

    return segments


@app.route('/test_lights', methods=['POST'])
def test_lights():
    set_global_settings()
    lights_list = request.get_json()
    for ip, positions in lights_list.items():
        # Validate positions list
        if not positions or not all(isinstance(pos, int) for pos in positions):
            return {'error': 'Invalid positions list'}, 400
        positions_json = json.dumps(positions)
        esp = db.get_esp_settings_by_ip(ip)
        light(positions_json, ip, esp, 1, True)
    return {'status': 'Lights controlled'}


def hex_to_rgb(hex_color):
    if hex_color:
        # Remove '#' if present in the hexadecimal color code
        if hex_color.startswith('#'):
            hex_color = hex_color[1:]

        # Check if the input is a valid hexadecimal color value
        if len(hex_color) != 6 or not all(c in '0123456789abcdefABCDEF' for c in hex_color):
            # If not valid, return default colors (red, green, blue)
            return [0, 255, 0]

        # Convert hexadecimal color code to RGB
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        return [r, g, b]
    else:
        return [0, 255, 0]


@app.route('/led/on', methods=['GET'])
def turn_led_on():
    set_global_settings()
    cancel_off_timer()
    app.previous_positions = {}  # Reset previous positions
    if request.method == 'GET':
        ips = get_unique_ips_from_database()
        for ip in ips:
            total_leds = get_total_leds(ip)
            on_data = {
                "on": True,
                "bri": round(255 * app.brightness),
                "transition": 5,
                "mainseg": 0,
                "seg": [
                    {
                        "id": 0,
                        "start": 0,
                        "stop": total_leds,
                        "grp": 1,
                        "spc": 0,
                        "of": 0,
                        "on": True,
                        "frz": False,
                        "cct": 127,
                        "set": 0,
                        "col": [hex_to_rgb(app.standbyColor)],
                        "fx": 0,
                        "sx": 128,
                        "ix": 128,
                        "pal": 0,
                        "c1": 128,
                        "c2": 128,
                        "c3": 16,
                        "sel": True,
                        "rev": False,
                        "mi": False,
                        "o1": False,
                        "o2": False,
                        "o3": False,
                        "si": 0,
                        "m12": 1
                    },
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0},
                    {"stop": 0}
                ]
            }
            send_request(ip, on_data)
        return jsonify({'success': True})


# Route to turn the LED off
@app.route('/led/off', methods=['GET'])
def turn_led_off():
    ips = get_unique_ips_from_database()
    cancel_off_timer()
    app.previous_positions = {}  # Reset previous positions
    for ip in ips:
        total_leds = get_total_leds(ip)
        on_data = {
            "on": False,
            "transition": 5,
            "seg": [
                {
                    "id": 0,
                    "start": 0,
                    "stop": total_leds,
                },
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0}
            ]
        }
        send_request(ip, on_data)
    return jsonify({'success': True})


# Route to turn the LED to Party
@app.route('/led/party', methods=['GET'])
def turn_led_party():
    cancel_off_timer()
    app.previous_positions = {}  # Reset previous positions
    set_global_settings()
    if request.method == 'GET':
        ips = get_unique_ips_from_database()
        for ip in ips:
            party_data = {"on": True, "bri": round(255 * app.brightness), "transition": 5, "mainseg": 0, "seg": [
                {"id": 0, "grp": 1, "spc": 0, "of": 0, "on": True, "frz": False, "bri": 255, "cct": 127, "set": 0,
                 "col": [[255, 255, 255], [0, 0, 0], [0, 0, 0]], "fx": 9, "sx": 128, "ix": 128, "pal": 0, "c1": 128,
                 "c2": 128, "c3": 16},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0},
                {"stop": 0}]}
            send_request(ip, party_data)
        return jsonify()


@app.route('/api/builds', methods=['GET', 'POST'])
def builds():
    if request.method == 'GET':
        return jsonify(db.read_builds()), 200
    elif request.method == 'POST':
        data = request.get_json()
        if not data or not data.get('name'):
            return jsonify({'error': 'Name required'}), 400
        build_id = db.write_build(data['name'])
        if data.get('items'):
            db.set_build_items(build_id, data['items'])
        return jsonify({'id': build_id, 'name': data['name']}), 201


@app.route('/api/builds/<int:build_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_build(build_id):
    if request.method == 'GET':
        build_items = db.get_build_items(build_id)
        return jsonify({'id': build_id, 'items': build_items}), 200
    elif request.method == 'PUT':
        data = request.get_json()
        if data.get('name'):
            db.update_build_name(build_id, data['name'])
        if 'items' in data:
            db.set_build_items(build_id, data['items'])
        return jsonify({'success': True})
    elif request.method == 'DELETE':
        db.delete_build(build_id)
        return jsonify({'success': True})


@app.route('/api/builds/<int:build_id>/execute', methods=['POST'])
def execute_build(build_id):
    try:
        warnings = db.execute_build(build_id)
        return jsonify({'success': True, 'warnings': warnings}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/translations', methods=['GET'])
def get_languages():
    # Define the directory containing the translation files, relative to the location of app.py
    translations_dir = os.getenv('TRANSLATIONS_DIR', os.path.join(os.path.dirname(__file__), 'static', 'translations'))

    try:
        # List all .json files in the translations directory
        languages = [f.split('.')[0] for f in os.listdir(translations_dir) if f.endswith('.json')]
        return jsonify(languages), 200
    except Exception as e:
        print(f"Error fetching languages: {e}")
        return jsonify({"error": "An error occurred fetching available languages"}), 500







if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=False)
